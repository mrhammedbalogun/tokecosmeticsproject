import json

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
    # Local name for the finest region level: "LGA" (NG), "Borough" (GB), "County" (US)…
    area_label = models.CharField(max_length=30, default="Area")

    class Meta:
        verbose_name_plural = "countries"

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"
