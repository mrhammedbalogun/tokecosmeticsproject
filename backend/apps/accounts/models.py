import secrets

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models.functions import Upper
from django.utils import timezone

from apps.core.models import TimeStampedModel

from .managers import UserManager

# Unambiguous alphabet — no 0/O/1/I/L, safe to read over the phone.
TOKE_ID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

# The address an anonymised account is left holding: `deleted-TK-XXXXXX@deleted.invalid`.
# `.invalid` is the RFC 2606 reserved TLD, so the sentinel can never route mail anywhere.
# It lives here rather than in `apps/accounts/tasks.py`, where it was written, because it
# is now read by two things that must agree: the sweep that WRITES it, and
# `UserManager.admin_visible()`, which is how every staff-facing read learns to skip those
# rows. Two copies of this string would mean a deleted customer stayed searchable.
ANONYMISED_EMAIL_DOMAIN = "@deleted.invalid"


class LegacyStore(models.TextChoices):
    """The three WooCommerce stores Plan-22 migrates from.

    Two DATABASES, three STORES: NG current and NG old share `tokecosm_wp481` under
    different table prefixes (`wp_` and `wp8n_`), and intl is `tokecosm_usawp100.wp8n_`.
    The values are the strings already written in `User.legacy_source`.
    """

    NG = "legacy_ng", "Nigeria — current store"
    NG_OLD = "legacy_ng_old", "Nigeria — old store (dead since Nov 2025)"
    INTL = "legacy_intl", "International (US/UK/CA)"


#: Which store wins when the same person exists on more than one, most-authoritative
#: first. The two LIVE stores beat the one dead since November 2025, because a customer
#: who used both most recently proved their password on a store that still takes orders.
#: NG current outranks intl on volume: 695 customers with orders against 13.
#:
#: This decides 17 rows — measured, not estimated: ng∩old 13, ng∩intl 1, old∩intl 3. The
#: audit's guess that "many old-NG customers likely re-registered" is wrong, which is why
#: a deterministic precedence list is enough and no manual reconciliation step is needed.
STORE_PRECEDENCE = (LegacyStore.NG, LegacyStore.INTL, LegacyStore.NG_OLD)


def best_store(stores) -> str:
    """The winning store from an iterable, by STORE_PRECEDENCE. Unknown values lose.

    Deterministic on purpose: the cutover delta run in Plan-27 re-imports the same people
    and must reach the same answer it reached at staging, or a customer's name and
    password would flip between two stores' versions of them.
    """
    ranked = [s for s in STORE_PRECEDENCE if s in set(stores)]
    return ranked[0] if ranked else ""


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

    # Which store this account's NAME AND PASSWORD came from, when it was migrated.
    # The WordPress ids themselves are NOT here — see LegacyIdentity below, which is a
    # row per store because one person can exist on all three.
    legacy_source = models.CharField(max_length=20, blank=True, choices=LegacyStore.choices)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "accounts_user"
        # TRIGRAM INDEXES FOR THE ADMIN SEARCH BOX, on `UPPER(col)` and not on the bare
        # column. That distinction is the whole point and it was measured rather than
        # assumed (Plan-16 Task 6): Django compiles `icontains` on PostgreSQL to
        # `UPPER(col::text) LIKE UPPER(%s)`, so a plain `gin(col gin_trgm_ops)` index — the
        # style used by `catalog.Product.product_name_trgm` — is NEVER consulted for it. At
        # 200k users the same query measured 88.7ms with no index, 89.1ms with bare-column
        # indexes, and 0.17ms with these. The bare index is not slower; it is simply never
        # used, which is the worse failure because the plan looks unremarkable.
        #
        # GIN + `gin_trgm_ops` rather than a btree because the pattern is `%term%` —
        # unanchored, so no btree can help at any price.
        indexes = [
            GinIndex(OpClass(Upper("email"), name="gin_trgm_ops"), name="user_email_trgm"),
            GinIndex(OpClass(Upper("first_name"), name="gin_trgm_ops"), name="user_first_trgm"),
            GinIndex(OpClass(Upper("last_name"), name="gin_trgm_ops"), name="user_last_trgm"),
            GinIndex(OpClass(Upper("toke_id"), name="gin_trgm_ops"), name="user_toke_id_trgm"),
        ]

    def __str__(self) -> str:
        return f"{self.email} ({self.toke_id})"

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class LegacyIdentity(TimeStampedModel):
    """One row per (store, WordPress user id) this account was migrated from.

    WHY A TABLE AND NOT COLUMNS. This replaced `User.legacy_wp_id` and
    `User.legacy_wp_id_intl` — two columns for three stores, which is the wrong shape and
    was caught while both were still empty, the last moment it was free to change. A third
    column would have been the obvious patch and would have been wrong again the moment a
    fourth store appeared, or the moment anyone asked "which stores was this customer on?"
    and got an answer assembled from column names.

    WHAT IT IS FOR, beyond provenance — two things that are not optional:

    * **The idempotency key.** Plan-27's cutover runs `migrate_customers --since` against
      live data, hours after the staging run. `(store, wp_user_id)` is what tells the
      second run "this is the same person", so it updates instead of creating a duplicate.
      Email cannot do this job: a customer who changes their email in WordPress between
      the two runs would import twice.
    * **What Plan-23 links orders with.** An order carries a WordPress customer id. Order
      linkage goes through this table FIRST and falls back to `billing_email` only for
      genuine guests — the spec's email-only linkage is lossy, because ordering on someone
      else's behalf makes billing email ≠ login email, and matching on it would attach a
      stranger's order to the wrong account.

    The unique constraint is on `(store, wp_user_id)` and NOT on `user`: one Django user
    legitimately holds up to three of these, which is exactly the 17 merged customers.
    """

    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="legacy_identities"
    )
    store = models.CharField(max_length=20, choices=LegacyStore.choices)
    wp_user_id = models.IntegerField()

    class Meta:
        constraints = [
            # A WordPress user id is unique WITHIN a store, never across them: NG user 42
            # and intl user 42 are different people. Store-scoped uniqueness is what makes
            # a re-run safe; a bare unique on wp_user_id would collide constantly.
            models.UniqueConstraint(
                fields=["store", "wp_user_id"], name="uniq_legacy_identity_store_wp_id"
            ),
        ]
        verbose_name_plural = "legacy identities"

    def __str__(self) -> str:
        return f"{self.store}#{self.wp_user_id} → {self.user_id}"


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


class StaffTOTP(TimeStampedModel):
    """One staff member's second factor. See `apps/accounts/totp.py` for the decisions;
    this docstring is about the SHAPE and why each field is what it is.

    **`secret_ciphertext` is Fernet, not a hash, and not plaintext.** A TOTP secret has
    to be recoverable in order to verify a code, so hashing is not available. Plaintext
    is: the nightly database backup leaves this box for S3, and a plaintext column there
    is the second factor for every administrator, free. The key lives in the environment
    (`TOTP_ENCRYPTION_KEY`), which a backup never contains, and it is deliberately
    separate from `SECRET_KEY` so the two can be rotated independently.

    **`confirmed_at` is the ONLY thing that counts as "enrolled".** A row with a secret
    and no `confirmed_at` is inert in both directions, and both directions matter:

    * the password step still returns a preauth token, so a half-finished enrolment
      (wrong app, closed tab) cannot lock anyone out of the flow that fixes it;
    * nothing anywhere treats it as a second factor, so an unconfirmed secret grants
      nothing.

    Calling enrol again REPLACES an unconfirmed secret and REFUSES a confirmed one. If
    enrol could overwrite a confirmed secret, anyone holding a stolen staff password
    could move the second factor onto their own phone, which would make TOTP decorative.
    The only route back to enrolment is a recovery code (or `manage.py
    reset_staff_totp`, which is root-only over SSH by design — see the runbook §6).

    **`last_verified_step` is the replay guard**, and it is a BigInteger because it
    holds a Unix-time-derived step number (currently ~6e7, growing forever). Any step at
    or below it is refused, so a code observed over a shoulder or in a phished form
    cannot be replayed inside its 90-second window. It is updated by an atomic
    conditional UPDATE in the same transaction as the success path, which is what makes
    two simultaneous submissions of one code resolve to exactly one winner.

    ONE ROW PER USER (`OneToOneField`): a staff member has one authenticator, and the
    alternative — several devices — would need a policy for which of them counts, which
    is a feature nobody has asked for and a hole nobody has audited. CASCADE because a
    deleted user has no second factor to keep.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="totp")
    secret_ciphertext = models.TextField(editable=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_verified_step = models.BigIntegerField(default=0)

    class Meta:
        verbose_name = "staff TOTP enrolment"
        verbose_name_plural = "staff TOTP enrolments"

    def __str__(self) -> str:
        return f"TOTP for {self.user_id} ({'confirmed' if self.confirmed_at else 'pending'})"

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_at is not None


class StaffRecoveryCode(TimeStampedModel):
    """One single-use bypass of the TOTP FACTOR — never of the ceremony.

    A code is only ever accepted from a caller who already holds a preauth token, which
    means password and Turnstile have already been verified. There is no bare
    recovery-code-to-session path, so a leaked code sheet on its own is worth nothing.
    Consuming one mints NO admin token: it voids the secret and the remaining codes and
    returns the holder to enrolment, which keeps "only TOTP-confirm mints an admin
    token" literally true with zero exceptions.

    **SHA-256, no work factor**, and lookup by digest. Same reasoning as the invite
    token: `secrets.token_hex(10)` is 80 bits, so there is nothing to enumerate and a
    slow KDF would only buy an attacker a CPU-DoS lever. The digest is uniquely indexed
    so the lookup is one equality match rather than a scan.

    `used_at` rather than deletion so that a burnt code is still visibly a burnt code —
    though the durable record is the ERROR-level `apps.security` line, since the whole
    set is deleted and replaced on the next enrolment.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="totp_recovery_codes")
    code_hash = models.CharField(max_length=64, unique=True, editable=False)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "used_at"])]

    def __str__(self) -> str:
        return f"recovery code for {self.user_id} ({'used' if self.used_at else 'unused'})"


class StaffEmailSecondFactor(TimeStampedModel):
    """One staff member's CHOICE of email codes as their second factor.

    There is deliberately no secret here: the codes themselves are short-lived, held
    hashed in the cache (`apps/accounts/email_otp.py`), and proved by control of the
    inbox — the same proof `/auth/password/reset/` runs on. This row records only that
    the choice was made and completed.

    **`confirmed_at` is the ONLY thing that counts as "enrolled"**, exactly as on
    `StaffTOTP`, and enrolment happens implicitly: the first email code a staff member
    verifies sets it (and issues their recovery codes). There is no separate enrol
    endpoint because, unlike TOTP, there is no secret to hand over first.

    THE TWO METHODS ARE MUTUALLY EXCLUSIVE, enforced in views rather than by a DB
    constraint: a confirmed `StaffTOTP` refuses the email path (or a stolen password
    could downgrade an authenticator user to inbox-strength security), and a confirmed
    row here refuses TOTP enrol (or the same password could move the factor onto an
    attacker's phone). The only routes between methods are a recovery code and
    `manage.py reset_staff_totp` — both void everything and return to the choice.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="email_second_factor")
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "staff email second factor"
        verbose_name_plural = "staff email second factors"

    def __str__(self) -> str:
        return (
            f"email 2FA for {self.user_id} "
            f"({'confirmed' if self.confirmed_at else 'pending'})"
        )

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_at is not None


class StaffTrustedDevice(TimeStampedModel):
    """One browser a staff member chose to trust for 30 days — a PRE-VERIFIED second
    factor, never a bypass of the ceremony.

    The raw token (`secrets.token_urlsafe(32)`, 256 bits) lives in exactly one place:
    an httpOnly cookie on the admin origin. It is accepted only inside TOTP-confirm,
    from a caller who already holds a preauth token — so password and Turnstile have
    already passed, and the only step it satisfies is the code prompt. A stolen cookie
    on its own opens nothing.

    **SHA-256, no work factor, lookup by digest** — the invite-token reasoning
    transfers exactly: 256 bits leaves nothing to enumerate, and the digest makes the
    lookup one indexed equality match.

    **`expires_at` is a hard ceiling, not a sliding window.** Using the device does not
    extend it; after 30 days the person types a code again. A sliding window would let
    one active browser hold the second factor forever, which is most of what the factor
    is for, given away.

    Revocation is DELETION, as with `StaffTOTP` on the recovery path: the row IS the
    capability, and the durable record of its life is the `apps.security` log. Rows die
    four ways — expiry, the revoke endpoint, a recovery code (the lost-device story
    must not leave sibling devices trusted), and `reset_staff_totp`.

    `label` is a trimmed User-Agent, for the human reading a device list or a log line.
    Display material only: it is attacker-choosable text, so it is scrubbed before
    logging and never part of any decision.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="trusted_devices")
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    label = models.CharField(max_length=120, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "expires_at"])]

    def __str__(self) -> str:
        return f"trusted device for {self.user_id} (expires {self.expires_at:%Y-%m-%d})"


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

    # The customer's pin (Plan-32b): captured by the Places pick or the confirm-your-pin
    # map step at checkout. Null is normal and permanent for addresses entered before
    # the rebuild or typed free-text without a pin — carrier quoting falls back to the
    # LGA centroid (core.Region), and nothing anywhere requires these to be set.
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    is_default_shipping = models.BooleanField(default=False)
    is_default_billing = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "addresses"

    def __str__(self) -> str:
        return f"{self.label or 'Address'} — {self.line1}, {self.country_code}"
