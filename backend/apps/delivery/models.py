from django.db import models

from apps.core.models import TimeStampedModel


class DeliveryOption(TimeStampedModel):
    KIND_CHOICES = [("manual", "Manual"), ("carrier", "Carrier API")]

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="manual")
    carrier_code = models.CharField(max_length=20, blank=True)  # "dhl", "gig" — Plan-32
    price = models.DecimalField(max_digits=12, decimal_places=2)  # flat price (common case)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    free_over = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # "The cost is unknown and will be quoted after the order" — NOT "the cost is zero".
    # Those are opposite meanings that a bare price=0 renders identically, and the
    # customer only ever sees the number. When true, services.py emits price=None so
    # there is no figure any client can render as "Free".
    quote_required = models.BooleanField(default=False)
    # Customer-visible text shown INSTEAD of a price. Carry an indicative range here
    # ("typically $35-70 to Europe") — it is the single biggest lever on the rate at
    # which customers decline the quote after they have already paid for goods.
    disclaimer = models.CharField(max_length=200, blank=True)
    min_days = models.PositiveSmallIntegerField()
    max_days = models.PositiveSmallIntegerField()
    countries = models.ManyToManyField("core.Country", blank=True, related_name="delivery_options")
    regions = models.ManyToManyField("core.Region", blank=True, related_name="delivery_options")
    is_active = models.BooleanField(default=True)
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.currency_id})"


class GigLga(TimeStampedModel):
    """One LGA as GIG's network knows it, synced nightly from `/lga/active` and
    `/homedelivery/active` (Plan-32a slice 2).

    `region` is the join to OUR world and the only column a human edits: the sync
    auto-matches by name (exact, then fuzzy — `gig.names`) but ONLY when the FK is
    null, so a hand-set mapping is never overwritten by a worse guess. An active
    GigLga with `home_delivery=True` and a mapped region with a centroid is the
    full precondition for offering GIG home delivery at checkout.

    Rows that vanish from GIG's list are deactivated, never deleted — the mapping
    work survives GIG toggling an LGA off and on again. Sandbox measured 303
    active / 103 home-delivery; production numbers replace them at go-live by
    pointing the same sync at the production base URL.
    """

    lga_name = models.CharField(max_length=100)      # GIG's spelling, verbatim
    state_name = models.CharField(max_length=100)    # GIG's spelling, verbatim
    gig_state_id = models.IntegerField()             # GIG's StateId (their numbering)
    is_active = models.BooleanField(default=True)
    home_delivery = models.BooleanField(default=False)
    region = models.ForeignKey(
        "core.Region", null=True, blank=True, on_delete=models.SET_NULL, related_name="gig_lgas"
    )
    synced_at = models.DateTimeField()

    class Meta:
        unique_together = [("state_name", "lga_name")]
        verbose_name = "GIG LGA"

    def __str__(self) -> str:
        flags = f"{'active' if self.is_active else 'inactive'}, hd={self.home_delivery}"
        return f"{self.state_name}/{self.lga_name} ({flags})"


class DeliveryOptionRate(models.Model):
    """Optional weight tiers. If an option has no rates, its flat `price` applies."""

    option = models.ForeignKey(DeliveryOption, on_delete=models.CASCADE, related_name="rates")
    min_weight_g = models.IntegerField(default=0)
    max_weight_g = models.IntegerField(null=True, blank=True)  # null = no upper bound
    price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["min_weight_g"]

    def __str__(self) -> str:
        upper = self.max_weight_g if self.max_weight_g is not None else "∞"
        return f"{self.option_id}: {self.min_weight_g}-{upper}g @ {self.price}"
