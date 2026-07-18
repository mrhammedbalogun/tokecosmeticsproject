import secrets

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

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
