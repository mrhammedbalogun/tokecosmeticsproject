"""Trusted devices — "don't ask again on this browser for 30 days".

The decisions live here, the HTTP shape in `views.py`, the storage in
`models.StaffTrustedDevice` — the same three-way split as `totp.py` and `email_otp.py`.

── WHAT A TRUSTED DEVICE IS, PRECISELY ───────────────────────────────────────────────

A pre-verified second factor, and NOTHING wider. The token is issued only by
TOTP-confirm at the moment a real code (TOTP or email) verifies with "trust this
device" ticked, and it is redeemed only inside the same confirm view, from a caller
who already holds a preauth token. Password and Turnstile therefore still run on every
login; the only step a trusted device skips is the code prompt. Amendment 6 survives
untouched — the mint site stays singular, and `trusted_device` is just a third way the
confirm view can be satisfied.

Two refusals keep it that narrow:

* **No confirmed second factor, no redemption.** A recovery code voids the factor AND
  this table (see the recovery view) — but belt and braces: a trust row that somehow
  survived its factor must not become the only factor.
* **Scoped to the user in the WHERE clause**, so one staff member's cookie is worth
  nothing against another's account even with the password in hand.

── HARD EXPIRY, NOT SLIDING ──────────────────────────────────────────────────────────

30 days from issuance, and use does not extend it. A sliding window would let one
open browser hold the second factor indefinitely, which is most of what the factor is
for, given away. 30 days is the ceiling for a small trusted staff; the cookie the
admin BFF sets carries the same Max-Age so browser and table expire together.

── WHY REDEMPTION IS AN ATOMIC CONDITIONAL UPDATE ────────────────────────────────────

Same discipline as recovery codes: the expiry predicate lives in the WHERE clause, so
"expired" is decided by the database under the row lock rather than by a Python read
that could act on a stale row. Redemption is NOT single-use — the same device verifies
every morning until it expires — so what the UPDATE writes is `last_used_at`, which is
what lets a device list answer "is this row a live browser or a forgotten one".
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.utils import timezone

from apps.core.log_safety import scrub

security_logger = logging.getLogger("apps.security")

# The ceiling, not a default anyone tunes: lengthening it widens how long a stolen
# laptop holds a pre-verified second factor, and there is no operational reason to.
TRUST_LIFETIME = timedelta(days=30)

# Per user. Not a security bound — a bound on junk: every row is a live credential
# record, and a staff member who trusts a new browser daily should shed the oldest
# rather than accumulate hundreds.
MAX_DEVICES_PER_USER = 10


def hash_device_token(raw: str) -> str:
    """SHA-256, no work factor, lookup by digest — the invite-token reasoning: 256
    bits leaves nothing to enumerate, and a slow KDF would be a CPU-DoS lever."""
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


def device_label(request) -> str:
    """A trimmed User-Agent for humans reading a device list. Attacker-choosable text:
    scrubbed, capped, and never part of any decision."""
    return scrub(request.META.get("HTTP_USER_AGENT", ""))[:120]


def issue_device_token(user, *, label: str = "") -> tuple[str, int]:
    """Mint a trust token for `user`. Returns (raw token, lifetime in seconds).

    The raw token exists in exactly two places after this returns: the response body
    that carries it to the admin BFF, and the httpOnly cookie the BFF sets. Never
    logged, never stored — the digest is the only durable copy.

    Housekeeping rides along: expired rows die, and the oldest rows beyond
    `MAX_DEVICES_PER_USER` die with them. Here rather than in a cron job because this
    is the only moment the table grows, so it is the only moment it needs pruning.
    """
    from apps.accounts.models import StaffTrustedDevice

    now = timezone.now()
    StaffTrustedDevice.objects.filter(user=user, expires_at__lte=now).delete()

    raw = secrets.token_urlsafe(32)
    StaffTrustedDevice.objects.create(
        user=user,
        token_hash=hash_device_token(raw),
        expires_at=now + TRUST_LIFETIME,
        label=label,
    )

    keep = StaffTrustedDevice.objects.filter(user=user).order_by(
        "-created_at"
    ).values_list("pk", flat=True)[:MAX_DEVICES_PER_USER]
    StaffTrustedDevice.objects.filter(user=user).exclude(pk__in=list(keep)).delete()

    security_logger.info("admin trusted device issued for %s", scrub(user.email))
    return raw, int(TRUST_LIFETIME.total_seconds())


def device_is_trusted(user, raw) -> bool:
    """A read with no side effects, for the login step's `device_trusted` hint.

    The hint decides which screen the admin app draws; REDEMPTION at the confirm step
    is the security decision. Both run the same predicate, so the hint can only be
    wrong across the seconds between the two calls — an expiry race that resolves to
    a code prompt, which is the safe direction.
    """
    from apps.accounts.models import StaffTrustedDevice

    if not isinstance(raw, str) or not raw.strip():
        return False
    return StaffTrustedDevice.objects.filter(
        user=user, token_hash=hash_device_token(raw), expires_at__gt=timezone.now()
    ).exists()


def redeem_device_token(user, raw) -> bool:
    """Satisfy the second factor with a trusted device. True only for a live row
    belonging to THIS user; stamps `last_used_at` in the same conditional UPDATE that
    checks expiry."""
    from apps.accounts.models import StaffTrustedDevice

    if not isinstance(raw, str) or not raw.strip():
        return False
    stamped = StaffTrustedDevice.objects.filter(
        user=user, token_hash=hash_device_token(raw), expires_at__gt=timezone.now()
    ).update(last_used_at=timezone.now())
    return stamped == 1


def revoke_all_devices(user) -> int:
    """Delete every trust row for `user`, returning how many died. Called by the
    revoke endpoint, by the recovery path (a lost device must not leave its siblings
    trusted), and by `reset_staff_totp`."""
    from apps.accounts.models import StaffTrustedDevice

    count, _ = StaffTrustedDevice.objects.filter(user=user).delete()
    return count
