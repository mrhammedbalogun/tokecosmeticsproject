from django.db import models

from apps.core.models import TimeStampedModel


class DeliveryOption(TimeStampedModel):
    KIND_CHOICES = [("manual", "Manual"), ("carrier", "Carrier API")]

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="manual")
    carrier_code = models.CharField(max_length=20, blank=True)  # "dhl", "gig" — Plan-32
    # One carrier, several services (Plan-32b): "home" = door delivery, "pickup" =
    # customer collects from a carrier location. Blank for manual options.
    carrier_service = models.CharField(max_length=20, blank=True)
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


class GigCentre(TimeStampedModel):
    """One GIG service centre, synced nightly from `serviceCentresByStation`
    (Plan-32b slice 1) — the pickup picker's data source.

    Same lifecycle discipline as GigLga: rows that vanish from GIG's list are
    deactivated, never deleted, and the ORDER keeps its own snapshot of the chosen
    centre (ruling 4) — this table answers "what can I pick today", the snapshot
    answers "where do I collect my parcel" forever."""

    gig_centre_id = models.IntegerField(unique=True)  # GIG's ServiceCentreId
    gig_station_id = models.IntegerField()
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=500, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    synced_at = models.DateTimeField()

    class Meta:
        verbose_name = "GIG centre"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({'active' if self.is_active else 'inactive'})"


class GigShipment(TimeStampedModel):
    """One order's GIG story, from checkout quote to delivered parcel (Plan-32a
    slice 4) — and the wallet-reconciliation trail Plan-20 reports aggregate.

    Born at ORDER PLACEMENT (status `quoted`, same transaction as the order —
    mirror of ShippingQuote's reasoning: created later it would be an absence,
    and absences are invisible). Enriched at capture with the waybill and the
    debited cost; advanced by the tracking poll.

    `cost` and `charged` are deliberately separate columns: cost is what GIG
    debits the wallet (the quote's GrandTotal), charged is what the customer
    paid us (0.00 under free_over, maybe marked-up someday). At reconciliation
    time their difference is exactly what we absorbed or earned.

    `create_unconfirmed` is the timeout limbo (plan ruling 1): the capture call
    timed out, GIG may or may not have created a waybill — and a retry could
    debit twice and dispatch two riders, so NOTHING retries automatically. A
    human checks with GIG (quoting `capture_api_id`) and resolves by hand.
    `abandoned` = the order died before capture; terminal, costs nothing.
    """

    STATUSES = [
        ("quoted", "Quoted"),
        ("created", "Waybill created"),
        ("in_transit", "In transit"),
        ("delivered", "Delivered"),
        ("create_unconfirmed", "Capture unconfirmed — check with GIG"),
        ("abandoned", "Abandoned"),
    ]
    # Nothing moves these forward: no capture may happen from them.
    TERMINAL = frozenset({"delivered", "abandoned"})

    order = models.OneToOneField(
        "orders.Order", on_delete=models.PROTECT, related_name="gig_shipment"
    )
    status = models.CharField(max_length=20, default="quoted", choices=STATUSES)
    quote = models.JSONField(default=dict)  # {price, breakdown, api_id} from checkout time
    cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    charged = models.DecimalField(max_digits=12, decimal_places=2)
    waybill = models.CharField(max_length=40, blank=True)
    capture_api_id = models.CharField(max_length=64, blank=True)
    label_url = models.URLField(blank=True)
    last_scan = models.JSONField(default=dict)  # newest raw tracking entry, verbatim
    last_tracked_at = models.DateTimeField(null=True, blank=True)
    # Centre pickup (32b ruling 4): the CHOSEN centre snapshotted at placement —
    # {"id": gig_centre_id, "name", "address"} — because centres close and move, and
    # "where do I collect my parcel" must answer from the order forever. Empty dict
    # for door-delivery shipments.
    centre = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "GIG shipment"

    def __str__(self) -> str:
        return f"{self.order_id}: {self.status}" + (f" ({self.waybill})" if self.waybill else "")


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
