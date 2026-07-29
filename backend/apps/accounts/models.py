import secrets

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel

from .managers import UserManager

# Unambiguous alphabet — no 0/O/1/I/L, safe to read over the phone.
TOKE_ID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def generate_toke_id() -> str:
    """'TK-' + 6 random chars from TOKE_ID_ALPHABET (~1.5e9 combinations)."""
    return "TK-" + "".join(secrets.choice(TOKE_ID_ALPHABET) for _ in range(6))


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    # Public, permanent customer id (e.g. "TK-7X4KQZ").
    toke_id = models.CharField(max_length=9, unique=True, editable=False)
    marketing_consent = models.BooleanField(default=False)

    # Set when the customer requests deletion. is_active flips to False immediately;
    # PII is anonymised 30 days later by apps.accounts.tasks.anonymize_deleted_accounts
    # (a grace window in case the request was a mistake or fraud recovery is needed).
    deletion_requested_at = models.DateTimeField(null=True, blank=True)
    # Set once the customer proves control of their inbox (verify-email or a completed
    # password reset). Gates legacy guest-order claiming — see apps.accounts.claims.
    email_verified_at = models.DateTimeField(null=True, blank=True)

    # Migration provenance (populated in Plan-22).
    legacy_source = models.CharField(max_length=20, blank=True)  # "", "legacy_ng", "legacy_ng_old", "legacy_intl"
    legacy_wp_id = models.IntegerField(null=True, blank=True)
    legacy_wp_id_intl = models.IntegerField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "accounts_user"

    def __str__(self) -> str:
        return f"{self.email} ({self.toke_id})"

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class StaffInvite(TimeStampedModel):
    """A pending invitation to become an administrator. See `apps/accounts/invites.py`
    for the flow; this docstring is about the SHAPE and why each field is what it is.

    AN OUTSTANDING INVITE IS A LIVE STAFF-CREATION CAPABILITY. Whoever holds the raw
    token can mint an `is_staff` account in the named role, so every field below is
    either part of bounding that capability in time or part of proving, afterwards,
    how a given administrator came to exist.

    **`role` is a ForeignKey to `auth.Group`, `on_delete=PROTECT`.** Roles ARE Groups
    (Plan-16 ruling 1); storing a name string would be a second source of truth that
    could drift from the group it names. PROTECT rather than CASCADE or SET_NULL:
    deleting a group with outstanding invites should fail loudly rather than either
    silently voiding an invite the Owner believes is live, or leaving one that grants a
    role nobody can name. The other way a group stops matching `rbac.ROLES` — a RENAME
    — is already caught twice (the `accounts.W001` system check at deploy time, and an
    ERROR log in `rbac.scopes_for_user` the moment a real person is affected), so this
    needs no code of its own.

    **`token_hash` is a SHA-256 digest, uniquely indexed; the raw token is never
    stored.** Deliberately NOT bcrypt/argon2, and the reasoning is worth writing down
    because "hash it with a slow KDF" is the reflex answer:

    * Slow KDFs exist to protect LOW-ENTROPY secrets — passwords, PINs — where the
      attacker's win condition is enumerating a small space. The token here is
      `secrets.token_urlsafe(32)`: 256 bits. There is no space to enumerate, so a work
      factor buys exactly zero security.
    * It costs on every submission, including junk ones. A public endpoint that does
      ~100ms of deliberate CPU work per unauthenticated request is a free CPU-DoS
      lever, which makes the "safer" choice the less safe one here.
    * A digest is also what lets the lookup be a single indexed equality match rather
      than a scan-and-compare over every outstanding row.

    Lookup is by digest, so nothing compares tokens directly. If that ever changes, the
    comparison must use `hmac.compare_digest` — a `==` on a secret is a timing oracle.

    **The raw token exists in exactly one place after creation: the invite email.** It
    is never logged, never returned by the API, and never written to the database. That
    means the accepted exposure is the recipient's mailbox and Resend's stored copy of
    the message — precisely the exposure `/auth/password/reset/` already carries, and
    the same trust argument justifies it (see `invites.accept_invite`).

    **`revoked_at` is the kill switch.** A mis-sent invite — wrong address, typo, wrong
    role — is otherwise live for the full TTL with no recourse. It is checked inside the
    same atomic claim as `accepted_at` and `expires_at`, so revoking cannot lose a race
    with an acceptance in flight.

    **`invited_by` is SET_NULL, and is only half the provenance trail.** The durable
    half is the `apps.security` log line written when the invite is created: rows can be
    deleted and users can be hard-deleted, log streams are append-only and shipped off
    the box. PROTECT here would couple deleting a person to invites they sent years ago,
    which is a strange thing to block on when the record that matters is elsewhere.

    RIDER ON PROMOTION, verified rather than assumed (see
    `test_a_promoted_users_old_customer_session_can_never_become_an_admin_one`).
    Accepting an invite for an address that already has a CUSTOMER account promotes that
    account, and does NOT blacklist its outstanding refresh tokens — a shopping session
    open at the time keeps working. That is acceptable because those tokens can never
    carry the admin audience claim: `AdminTokenObtainPairSerializer.get_token` is the
    only place `toke_aud` is ever written, and `/auth/token/refresh/` copies the claims a
    token already has rather than adding any. A customer token therefore cannot be
    refreshed into an admin one, before or after promotion.
    """

    email = models.EmailField()
    role = models.ForeignKey(
        "auth.Group", on_delete=models.PROTECT, related_name="staff_invites"
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    invited_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staff_invites_sent",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"invite {self.email} -> {self.role_id} ({self.state})"

    @property
    def state(self) -> str:
        """One word for the admin UI. NOT the authority on whether an invite can be
        claimed — that decision is made by the database, inside the conditional UPDATE
        in `invites.claim`, because anything computed in Python has already gone stale
        by the time it is acted on."""
        if self.revoked_at is not None:
            return "revoked"
        if self.accepted_at is not None:
            return "accepted"
        if self.expires_at <= timezone.now():
            return "expired"
        return "pending"


class Address(TimeStampedModel):
    """Structured, per-country address. Validation rules live in core.address_rules."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=40, blank=True)  # "Home", "Office"
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=32, blank=True)

    line1 = models.CharField(max_length=255)
    line2 = models.CharField(max_length=255, blank=True)
    country_code = models.CharField(max_length=2)  # any ISO country (worldwide shipping)

    # Structured region links where region data exists (e.g. NG state + LGA).
    state_region = models.ForeignKey(
        "core.Region", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    area_region = models.ForeignKey(
        "core.Region", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # Free-text fallbacks for countries without region data.
    city_text = models.CharField(max_length=100, blank=True)
    state_text = models.CharField(max_length=100, blank=True)
    postcode = models.CharField(max_length=20, blank=True)

    is_default_shipping = models.BooleanField(default=False)
    is_default_billing = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "addresses"

    def __str__(self) -> str:
        return f"{self.label or 'Address'} — {self.line1}, {self.country_code}"
