"""Issuing and claiming staff invites — the only path by which a new administrator
comes into existence.

This module holds the decisions; `views.py` holds the HTTP shape. The split matters
for one test in particular: the concurrency test drives `accept_invite` from two real
threads, which is only possible because the claim is a function rather than something
buried in a request/response cycle.

THE CLAIM IS ONE ATOMIC CONDITIONAL UPDATE, and that is the whole of the single-use
guarantee. Written the obvious way — read the row, check the three conditions in
Python, then save — two accepts arriving together both read a pending invite, both
pass, and the second either creates a duplicate account or resets the first one's
password. Instead the predicate lives in the WHERE clause:

    UPDATE ... SET accepted_at = now
     WHERE id = ? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now

The database evaluates that while holding the row lock, so of two concurrent callers
exactly one sees a rowcount of 1. The loser re-reads the row to find out WHY it lost —
which is safe to do non-atomically, because by then it is only deciding what to say.

TOKEN HANDLING. `secrets.token_urlsafe(32)` is 256 bits; the database stores only its
SHA-256 digest, uniquely indexed, and lookup is a single equality match on that digest.
See the `StaffInvite` docstring for why this is deliberately not bcrypt/argon2 and why
the raw token exists nowhere but the invite email.

WHY ACCEPTING ALWAYS SETS A PASSWORD, even for an account that already had one. An
invited address may already exist as a CUSTOMER — the store owner shops on his own
store, so refusing that case would break the only real user, and creating a second
account is a unique-constraint violation pretending to be an option. So promotion it
is. The danger promotion carries is that a shopping password chosen years ago,
possibly reused, possibly in a breach corpus, silently becomes an ADMINISTRATOR's
password. Setting a new one unconditionally is what removes it: after acceptance, no
customer-era credential exists on the account.

The trust argument for letting an invite set a password at all: possession of the
token proves control of the invited inbox, which is exactly the trust level
`/auth/password/reset/` already runs on. This is reset-with-promotion, not something
weaker.
"""
from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import StaffInvite

# 32 bytes -> 256 bits, rendered as ~43 URL-safe characters. Sized so that guessing is
# not a threat that has to be mitigated by anything else (see the throttle on the
# accept view, which exists to cap junk VOLUME rather than guesses).
TOKEN_BYTES = 32


class InviteRejected(Exception):
    """A submitted token cannot be claimed.

    `reason` is one of `unknown`, `revoked`, `used`, `expired`. The VIEW decides how
    much of that to tell the caller — three of the four share one uniform message
    because distinguishing them would confirm that a token was once real. The reason is
    still carried here because the security log needs it: an unknown token and an
    expired one are very different events to whoever reads the alerts.
    """

    def __init__(self, reason: str, invite: StaffInvite | None = None):
        super().__init__(reason)
        self.reason = reason
        self.invite = invite


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw: str) -> str:
    """The value stored and looked up. SHA-256 rather than a slow KDF — see the
    `StaffInvite` docstring; the short version is that a work factor buys nothing
    against 256 bits and hands an unauthenticated endpoint a CPU-DoS lever."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def invite_ttl():
    from datetime import timedelta

    return timedelta(hours=settings.STAFF_INVITE_TTL_HOURS)


def issue_invite(*, email: str, role, invited_by) -> tuple[StaffInvite, str]:
    """Create an invite and return it with the RAW token, which the caller must send by
    email and then drop. It is returned rather than stored because this is the only
    moment it will ever exist in this process."""
    raw = new_token()
    invite = StaffInvite.objects.create(
        email=email,
        role=role,
        token_hash=hash_token(raw),
        expires_at=timezone.now() + invite_ttl(),
        invited_by=invited_by,
    )
    return invite, raw


def find_invite(raw_token: str) -> StaffInvite | None:
    """The indexed digest lookup. Separate from `claim` because the accept view has to
    know whether a token is valid BEFORE it decides whether to touch a throttle bucket
    — see `StaffInviteAcceptView` for why that order is inverted on purpose."""
    if not isinstance(raw_token, str) or not raw_token:
        return None
    return StaffInvite.objects.filter(token_hash=hash_token(raw_token)).first()


def _reason(invite: StaffInvite, now) -> str:
    """Why a claim lost. Order matters: a revoked invite that has also expired is
    reported as revoked, because revocation was a deliberate act and expiry was not."""
    if invite.revoked_at is not None:
        return "revoked"
    if invite.accepted_at is not None:
        return "used"
    if invite.expires_at <= now:
        return "expired"
    # The predicate matched nothing yet none of the three conditions holds — only
    # reachable if the row changed between the UPDATE and this re-read, i.e. someone
    # else claimed it in the microseconds since. Treat it as used, which is what it is.
    return "used"


def claim(raw_token: str) -> StaffInvite:
    """Mark an invite accepted, atomically. Raises `InviteRejected`.

    Must be called inside the caller's transaction so that the claim and whatever the
    caller does with it either both happen or neither does — otherwise a failure while
    creating the user would leave a burnt invite and no account.
    """
    invite = find_invite(raw_token)
    if invite is None:
        raise InviteRejected("unknown")

    now = timezone.now()
    claimed = StaffInvite.objects.filter(
        pk=invite.pk,
        accepted_at__isnull=True,
        revoked_at__isnull=True,
        expires_at__gt=now,
    ).update(accepted_at=now)
    if claimed != 1:
        invite.refresh_from_db()
        raise InviteRejected(_reason(invite, now), invite=invite)

    invite.accepted_at = now
    return invite


@transaction.atomic
def accept_invite(raw_token: str, *, password: str):
    """Claim an invite and produce the staff account it promises.

    Returns `(invite, user, created)`. `created` is False when an existing customer was
    promoted, which the caller logs — "a customer account became an administrator" and
    "a new account was created" are different sentences to whoever reads the security
    stream.

    Everything is inside ONE transaction with the claim. If the user work fails, the
    claim rolls back with it and the invite is still usable; if the claim loses the
    race, no account is created.
    """
    User = get_user_model()
    invite = claim(raw_token)

    user = User.objects.filter(email__iexact=invite.email).first()
    created = user is None
    if created:
        # Through the manager, not `User(...)`: `toke_id` is allocated in
        # `UserManager._create_user` (with a collision retry), and a user saved around
        # it gets an empty toke_id — which is unique-indexed, so the SECOND such account
        # would fail with an IntegrityError about a field nobody set.
        user = User.objects.create_user(
            email=invite.email, password=password, is_staff=True
        )
    else:
        user.is_staff = True
        # UNCONDITIONAL, including for an account that already had a password. See the
        # module docstring: this is the line that stops a customer-era credential from
        # silently becoming an administrator's.
        user.set_password(password)
        # An invited address may belong to a customer who had asked us to close their
        # account. Accepting a staff invite at that address is a newer and more
        # deliberate statement of intent than the pending deletion, so the request is
        # cleared rather than left to run: `anonymize_deleted_accounts` sweeps on
        # `is_active=False AND deletion_requested_at < cutoff`, and a staff account
        # carrying an expired clock would be scrubbed the moment anyone deactivated it.
        user.is_active = True
        user.deletion_requested_at = None
        user.save(update_fields=["is_staff", "password", "is_active", "deletion_requested_at"])

    # Accepting proves control of the inbox — the same proof `/auth/password/reset/`
    # accepts, where it likewise marks the address verified.
    if user.email_verified_at is None:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])

    user.groups.add(invite.role)
    return invite, user, created
