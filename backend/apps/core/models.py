import json

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base adding created_at / updated_at to every model that needs it."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SiteSetting(TimeStampedModel):
    """Singleton-ish typed key/value store for tunable site settings."""

    VALUE_TYPES = [("str", "String"), ("int", "Integer"), ("bool", "Boolean"), ("json", "JSON")]

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True)
    value_type = models.CharField(max_length=10, choices=VALUE_TYPES, default="str")

    def __str__(self) -> str:
        return self.key

    def typed_value(self):
        if self.value_type == "int":
            return int(self.value)
        if self.value_type == "bool":
            return self.value.strip().lower() in ("1", "true", "yes", "on")
        if self.value_type == "json":
            return json.loads(self.value)
        return self.value

    @classmethod
    def get_typed(cls, key, default=None):
        try:
            return cls.objects.get(key=key).typed_value()
        except cls.DoesNotExist:
            return default


class Redirect(TimeStampedModel):
    """Old→new URL redirect, served by the storefront middleware (Plan-24)."""

    old_path = models.CharField(max_length=500, unique=True)
    new_path = models.CharField(max_length=500)
    status_code = models.PositiveSmallIntegerField(default=301)
    hits = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.old_path} -> {self.new_path} ({self.status_code})"


class Region(models.Model):
    """Geographic tree per country (e.g. NG state -> LGA). Seeded in Plan-08."""

    LEVELS = [("state", "State/Region"), ("city", "City"), ("area", "LGA/Area")]

    country_code = models.CharField(max_length=2, db_index=True)  # ISO code, any country
    name = models.CharField(max_length=100)
    level = models.CharField(max_length=10, choices=LEVELS)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    is_active = models.BooleanField(default=True)
    # Centre-point of the region, used to satisfy carrier APIs that demand coordinates
    # (GIG requires them; measured 2026-08-02, an LGA centroid prices within ~3% of the
    # street address — docs/gigimplementationresearch.md §2d). Null is honest: a region
    # without a centroid is simply never offered a coordinate-based carrier. Loaded by
    # `manage.py load_lga_centroids`.
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        unique_together = [("country_code", "parent", "name")]

    def __str__(self) -> str:
        return f"{self.name} ({self.country_code}/{self.level})"


class Currency(models.Model):
    """ISO-4217 currency used for pricing (NGN, GBP, USD, CAD)."""

    code = models.CharField(max_length=3, primary_key=True)       # "NGN"
    symbol = models.CharField(max_length=8)                       # "₦"
    decimal_places = models.PositiveSmallIntegerField(default=2)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.code


class Country(models.Model):
    """A market the store sells into. Drives currency + flat tax + pricing context.

    Note: US/CA sales-tax-by-state is OUT of MVP scope — one flat configurable
    rate per country here; refine post-launch (see docs/architecture.md).
    """

    code = models.CharField(max_length=2, primary_key=True)       # "NG"
    name = models.CharField(max_length=100)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)               # NG
    is_rest_of_world = models.BooleanField(default=False)         # the "ZZ" catch-all
    tax_rate_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    prices_include_tax = models.BooleanField(default=True)
    # Local names for the region levels (Countries_breakdown mapping). Level 1:
    # "State" (NG/US), "Province" (CA), "Country" (GB's constituent countries).
    state_label = models.CharField(max_length=30, default="State")
    # Level 2, the finest: "LGA" (NG), "District" (GB), "County" (US), "Municipality" (CA).
    area_label = models.CharField(max_length=30, default="Area")

    class Meta:
        verbose_name_plural = "countries"

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class AuditLogImmutable(Exception):
    """Raised by `AuditLog.save()` when something tries to rewrite an existing row.

    A plain `Exception` rather than a `ValidationError` on purpose: this is not a user
    input problem the API should turn into a 400, it is a programming error that must
    reach a 500 and a Sentry event.
    """


class AuditLog(TimeStampedModel):
    """Who did what, on the admin surface. Plan-16 Task 4.

    WHAT THIS IS FOR, because it changes every field choice below. Tasks 1-3b built a
    fence: an audience claim, scopes, mandatory TOTP. Their tests prove an outsider
    cannot get in. This table is worth nothing against that attacker — it is for the
    person who is already inside WITH A KEY. An insider, or somebody holding a staff
    session they stole. The only question it has to answer is "what did that key do,
    and when".

    ── THE FIELDS, AND WHY EACH ONE ────────────────────────────────────────────────

    `actor` is SET_NULL rather than CASCADE or PROTECT. CASCADE would mean deleting a
    staff account deletes the record of what it did, which is the single most obvious
    way for an insider to clean up after themselves. PROTECT would mean a staff account
    can never be deleted at all once it has touched anything, which turns an ordinary
    offboarding into a support ticket.

    `actor_email` is the reason SET_NULL is safe. It is a SNAPSHOT taken at write time
    and never refreshed: when the FK goes NULL the row still says who. It is also
    deliberately not a FK to anything, so nothing can cascade it away.

    `token_jti` is the claim that turns "X did this" into "X's session from Tuesday
    14:02 did this". Actor plus timestamp plus IP already identifies WHO; the jti
    identifies WHICH LOGIN — which specific TOTP ceremony minted the credential that
    acted. That is the field you need on the day a staff TOKEN is stolen rather than a
    staff member being malicious, because it is what separates the rows that person
    really made from the rows made with their stolen session.

    Deliberately ABSENT: the audience claim. Every row here is written by a view behind
    `AdminJWTAuthentication`, so the claim can only ever hold one value, and a column
    that can only ever hold one value is decoration that later reads as evidence.

    `client_ip` uses `apps.accounts.throttling.client_ip`, which ignores
    X-Forwarded-For entirely and reads `CF-Connecting-IP` then `REMOTE_ADDR`. See that
    function: XFF is caller-controlled on the direct-to-API path, so recording it would
    put an attacker-chosen string in the evidence column.

    `changes` holds ONLY keys a serializer or view explicitly allowlisted. See
    `apps/core/audit.py` for why an allowlist rather than a denylist, and for the 8KB
    cap.

    ── IMMUTABILITY, HONESTLY SCOPED ───────────────────────────────────────────────

    There is no hash chain here and that is a decision, not an omission. Chaining
    without an external anchor is theatre: anybody who can write the table can re-chain
    it in one UPDATE, so the chain would assert a guarantee that does not exist — and
    this project has been bitten three times by controls that only existed in a
    comment. What is here instead is three cheap, real things:

    1. `save()` refuses to rewrite an existing row (below), so no application code path
       can update one by accident.
    2. A Postgres trigger (`0006_auditlog_append_only`) refuses UPDATE of every column
       except `changes` and `actor_id`, and refuses DELETE outright. That one holds
       even against code that bypasses the ORM, which is what makes it worth having.
    3. Every row is mirrored to the `apps.security` log as KEYS AND IDS ONLY, so the
       database is not the only copy.

    The honest sentence, which is also in `docs/runbooks/admin-gate.md`: **audit rows
    are tamper-RESISTANT against application-level compromise, not tamper-EVIDENT
    against root or a database superuser.** True off-box WORM storage belongs with the
    Plan-22 S3 work (bucket versioning plus a credential that cannot delete); it is
    noted there and deliberately not built here.

    ── RETENTION ───────────────────────────────────────────────────────────────────

    Indefinite. No window is configured, and inventing a number ("90 days", "2 years")
    would be picking a compliance posture nobody has decided on. Revisit at Plan-27.
    What DOES happen is redaction: `apps/accounts/tasks.anonymize_deleted_accounts`
    hollows out the VALUES in `changes` for rows about a deleted customer and keeps the
    keys, the object id, the actor, the IP and the timestamp — so "staff member X
    edited customer 123's address at 14:02" stays provable without the address.
    """

    # Deliberately not `Meta.ordering`: this table is append-only and read newest-first
    # in exactly one place (the list endpoint), which says so itself.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    # 254 is the RFC 5321 cap on an address; `blank=True` covers the one case where a
    # row can be written with no human behind it (a management command), which is not
    # possible today but is cheaper to allow than to discover later.
    actor_email = models.CharField(max_length=254, blank=True)
    token_jti = models.CharField(max_length=64, blank=True)
    client_ip = models.CharField(max_length=45, blank=True)  # 45 = longest IPv6 text form
    model_label = models.CharField(max_length=100, blank=True)  # "orders.order"
    object_id = models.CharField(max_length=64, blank=True)     # pk, order number or slug
    action = models.CharField(max_length=64)                    # "create", "read", "refund"…
    changes = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["model_label", "object_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_email} {self.action} {self.model_label}"

    def save(self, *args, **kwargs):
        """INSERT only. Rewriting an existing row raises.

        `_state.adding` rather than `pk is None`, because assigning a pk to a fresh
        instance is a legitimate thing to do (fixtures, explicit ids) and would make a
        pk check refuse a genuine insert. `adding` is False only once the row has been
        loaded from, or written to, the database.

        This is the FIRST of the three fences in the class docstring and the weakest of
        them: it is bypassed by `QuerySet.update()`, by raw SQL, and by anything that
        is not this method. It is here because it makes the accidental case — a future
        view that fetches a row and calls `.save()` — impossible, and because a test
        can assert it. The fence that holds against deliberate rewriting is the
        database trigger.
        """
        if not self._state.adding:
            raise AuditLogImmutable(
                "AuditLog rows are append-only; an existing row cannot be re-saved."
            )
        return super().save(*args, **kwargs)
