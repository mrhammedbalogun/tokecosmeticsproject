from django.conf import settings
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


class SenderLocation(TimeStampedModel):
    """One Toke fulfilment point GIG can collect from (Plan-34).

    The sender used to be six `GIG_SENDER_*` env vars; multiple shops made it data.
    Selection is nearest-active-to-the-receiver by haversine (`gig/origins.py`) and
    the chosen row is SNAPSHOTTED onto `GigShipment.origin` at placement — edits
    here never rewrite what an in-flight order was quoted from. Zero active rows =
    the env-var fallback, byte-for-byte today's behaviour, so this table can be
    emptied without breaking a checkout.

    The pin is load-bearing twice over: GIG prices from it (Ogudu vs Ikorodu
    measured +85%) and the rider drives to it. `phone` is who GIG calls to
    coordinate the pickup — it must reach THIS shop's counter.

    Since Plan-40 a row can ALSO be a customer-facing pickup store
    (`customer_pickup=True`): checkout offers "Pickup at Toke Cosmetics Store" at ₦0
    to any NG/NGN address in the same `state_region`, and the chosen row is
    snapshotted onto `Order.pickup_store` at placement. The two roles are
    independent — an opted-in store still serves as a GIG origin, and a GIG-only
    origin never shows to customers.
    """

    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)  # strict E.164, judged by core.phones
    address = models.CharField(max_length=500)
    locality = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    # DISPLAY ONLY (Plan-35): human filing for a table that will grow — nothing routes
    # on these for GIG. The PIN is the only GIG routing input (origins.select_origin is
    # pure haversine); typing "Lagos" here must never move a quote. Customer store
    # pickup (Plan-40) routes on `state_region` below, never on this free text.
    state = models.CharField(max_length=100, blank=True)
    lga = models.CharField(max_length=100, blank=True)
    # Customer store pickup (Plan-40). `customer_pickup` opts this location into the
    # checkout "Pickup at Toke Cosmetics Store" card; GIG-only origins and warehouses
    # keep it off. Matching is BY STATE, deliberately not by LGA: every opted-in Lagos
    # location shows to every Lagos customer. `state_region` is the canonical
    # core.Region (level="state") the match runs on — an FK, not the free-text `state`
    # above, so a spelling can never hide a store from its own state.
    customer_pickup = models.BooleanField(default=False)
    state_region = models.ForeignKey(
        "core.Region", null=True, blank=True, on_delete=models.PROTECT,
        related_name="pickup_store_locations", limit_choices_to={"level": "state"},
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "GIG sender location"
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
    # Multi-origin (Plan-34): the SENDER location this shipment was quoted from —
    # `gig/origins.py` `as_snapshot()` shape — snapshotted at placement for the same
    # reason as `centre`: capture must ship from exactly what was priced, even after
    # the row is edited or deactivated. Empty dict = the env-var origin (pre-Plan-34
    # shipments and the zero-rows fallback); capture then reads settings.
    origin = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "GIG shipment"

    def __str__(self) -> str:
        return f"{self.order_id}: {self.status}" + (f" ({self.waybill})" if self.waybill else "")


class AajShipment(TimeStampedModel):
    """One order's AAJ Express story, from checkout quote to delivered parcel
    (Plan-43) — GigShipment's sibling for a carrier with a two-step booking API.

    Born at ORDER PLACEMENT (status `quoted`, same transaction as the order — the
    GigShipment reasoning verbatim: created later it would be an absence, and
    absences are invisible). Capture is TWO calls: create-booking (free, yields
    `booking_id`, status `booked`) then process-booking (THE MONEY CALL — charges
    our AAJ account, yields `tracking_id` + label, status `created`). Advanced by
    the tracking poll; AAJ has no webhooks.

    `cost` and `charged` are deliberately separate columns — and for AAJ they
    differ by design, not only under free_over: the customer is priced from AAJ's
    RETAIL `/quote` (the documented, booking-free endpoint) while create-booking
    under our partner key prices ~14% lower (measured 2026-08-23: ₦2,779 retail vs
    ₦2,392 booked, intra-Lagos ≤1 kg). That gap is an invisible margin BEFORE any
    Plan-41 fee mask; both figures sit here so the deliveries table can show it.
    `quote_total` is the retail figure the customer was priced from (pre-mask),
    kept beside `charged` because a free_over order charges 0 and would otherwise
    lose the number. Both prices are VAT-INCLUSIVE (AAJ's 7.5% rides inside
    `total`) — never add tax on top of an AAJ delivery figure.

    `create_unconfirmed` is the ambiguity lane: process-booking failed or timed
    out AND the follow-up get-booking read could not settle whether money moved.
    MEASURED: a 500 "Credit facility cannot be charged" still minted a shipment
    record (tracking id + label, booking `paid:false`), so a refusal is not proof
    of no side-effect — capture.py reconciles after EVERY non-success. A human
    resolves this lane from the order page; nothing retries it blind.

    `booked` can be re-captured (process only, same booking — never a second
    create) and is released by the abandon lane, which also asks AAJ to delete the
    unpaid booking so customer PII does not sit in their system as a DUE record.
    `voided` and `returned` are terminal for the POLL but a voided shipment can be
    captured again (fresh booking: the void use-case is "wrong address, fix and
    resend"); the voided attempt's ids stay in the order timeline.
    """

    STATUSES = [
        ("quoted", "Quoted"),
        ("booked", "Booked — not yet paid"),
        ("created", "Shipment created"),
        ("in_transit", "In transit"),
        ("delivered", "Delivered"),
        ("returned", "Returned to sender"),
        ("voided", "Voided"),
        ("create_unconfirmed", "Capture unconfirmed — check with AAJ"),
        ("abandoned", "Abandoned"),
    ]
    # Nothing moves these forward through capture: no booking may happen from them.
    TERMINAL = frozenset({"delivered", "returned", "abandoned"})
    # Capture (create or process) may start from these.
    CAPTURABLE = frozenset({"quoted", "booked", "voided"})

    order = models.OneToOneField(
        "orders.Order", on_delete=models.PROTECT, related_name="aaj_shipment"
    )
    status = models.CharField(max_length=20, default="quoted", choices=STATUSES)
    quote = models.JSONField(default=dict)  # {price, breakdown, eta_days, origin} from checkout
    quote_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    charged = models.DecimalField(max_digits=12, decimal_places=2)
    booking_id = models.CharField(max_length=40, blank=True)      # AAJ booking _id
    tracking_id = models.CharField(max_length=40, blank=True)     # AAJ shipment tracking id
    aaj_shipment_id = models.CharField(max_length=40, blank=True)  # AAJ shipment _id (void key)
    label_url = models.URLField(blank=True)
    last_scan = models.JSONField(default=dict)  # newest raw tracking event, verbatim
    last_status = models.IntegerField(null=True, blank=True)  # AAJ numeric status at last poll
    last_tracked_at = models.DateTimeField(null=True, blank=True)
    # The SENDER origin this shipment was quoted from — `aaj/origins.py`
    # `as_snapshot()` shape — snapshotted at placement so capture books from exactly
    # what was priced (the origin's STATE prices the zone) even after the row is
    # edited or deactivated.
    origin = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "AAJ shipment"

    def __str__(self) -> str:
        ref = self.tracking_id or self.booking_id
        return f"{self.order_id}: {self.status}" + (f" ({ref})" if ref else "")


class DeliveryPartner(TimeStampedModel):
    """A small local courier with no API (Plan-39): flat per-zone rates the partner
    maintains THEMSELVES through the partner portal (`partner_views.py`).

    `user` is the portal login — an ordinary auth row with `is_staff=False` that
    exists only to hold the email + password; it is never a customer and never staff.
    Portal tokens carry the `toke-partner` audience (`accounts/authentication.py`),
    so they open exactly the `/api/v1/partner/` surface and nothing else.

    `is_active` is the staff kill-switch. `IsDeliveryPartner` re-reads it from the
    database on every portal request (same reasoning as the admin `is_staff` check:
    a claim outlives revocation, a DB read does not), and checkout skips every zone
    of an inactive partner — one flip removes the partner from both surfaces at once.
    """

    name = models.CharField(max_length=100)  # customer-facing: "BrandnPack"
    code = models.SlugField(max_length=20, unique=True)  # "brandnpack"
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="delivery_partner"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "delivery partner"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({'active' if self.is_active else 'inactive'})"


class PartnerZone(TimeStampedModel):
    """One row of a partner's rate card (Plan-39): an LCDA inside an LGA, the areas it
    covers, and a flat NGN price — weight- and origin-independent by the partner's own
    pricing model, which is why there is no tier table here.

    `price` is NULLABLE and null means "the partner has not set a price yet", not
    "free" — the source doc arrived with 8 such rows (Badagry, Epe, and two
    range-priced rows Hammed ruled to skip). services.py only ever offers rows with
    `is_active=True` AND a non-null price, so a null-priced row is visible in the
    portal (badged "needs a price") but can never render as ₦0 at checkout.

    Rows are matched to an address through `lga_region` (a `core.Region` at
    level="area"); the LCDA itself is deliberately NOT a Region — Hammed's ruling was
    to leave the LGA address structure untouched and offer every matching LCDA row as
    its own delivery option, labelled with `lcda_name`.

    Orders snapshot only the composed option NAME (orders.Order.delivery_option_name),
    so partner edits and deletes never touch a placed order.
    """

    partner = models.ForeignKey(DeliveryPartner, on_delete=models.CASCADE, related_name="zones")
    lga_region = models.ForeignKey(
        "core.Region", on_delete=models.PROTECT, related_name="partner_zones"
    )
    lcda_name = models.CharField(max_length=100)
    # The doc's "Major Locations & Landmarks" — shown to the customer verbatim as
    # "Areas covered: …" on the option card.
    areas_covered = models.CharField(max_length=300)
    dispatch_zone = models.CharField(max_length=100, blank=True)
    # NGN, implicitly: partner options are only appended to NGN orders (services.py).
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    min_days = models.PositiveSmallIntegerField(default=1)
    max_days = models.PositiveSmallIntegerField(default=3)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "partner zone"
        ordering = ["lga_region__name", "lcda_name"]

    def __str__(self) -> str:
        state = "live" if self.is_active and self.price is not None else "hidden"
        return f"{self.partner.code}: {self.lga_region.name} / {self.lcda_name} ({state})"


class PartnerShipment(TimeStampedModel):
    """One order's hand-off to a delivery partner — GigShipment's analogue for
    couriers with no API. Born at ORDER PLACEMENT, same transaction as the order
    (the ShippingQuote/GigShipment reasoning verbatim: created later it would be
    an absence, and absences are invisible — this row is how the deliveries table
    learns the order goes out with a partner at all).

    DELIBERATELY NO STATUS COLUMN. GIG's lifecycle exists because GIG feeds it
    (webhooks + polling); a partner feeds nothing, staff already move the ORDER's
    status by hand, and a second hand-maintained status would only drift from the
    first. The order stays the single status authority and the admin table renders
    it. The one fact that column cannot keep is `delivered_at` below.

    `cost` and `charged` mirror GigShipment's split: cost is the partner's raw
    zone price (what the partner invoices us), charged is what the customer paid —
    since Plan-41 their difference is exactly the fee mask. Cost is nullable for
    the rows where the raw price is genuinely unknowable (a zone deleted mid-
    checkout, ambiguous backfill matches), never coerced to 0.

    `delivered_at` is stamped by the order state machine's deferred-effects lane
    when the order reaches `delivered` — machine-written, never hand-edited. It
    deliberately SURVIVES a later refund: `delivered -> refunded` rewrites the
    order's status, but "the partner did deliver this" is a fact the partner's
    invoice reconciliation still needs (the same falsified-trail reasoning that
    keeps a refunded GigShipment's waybill and wallet debit).
    """

    order = models.OneToOneField(
        "orders.Order", on_delete=models.PROTECT, related_name="partner_shipment"
    )
    partner = models.ForeignKey(
        DeliveryPartner, on_delete=models.PROTECT, related_name="shipments"
    )
    # The chosen PartnerZone at placement — {"id", "lcda", "areas", "dispatch_zone",
    # "min_days", "max_days"}. A SNAPSHOT, not an FK: the partner edits and deletes
    # their own rate-card rows through the portal, and a placed order must never
    # shift under them. The race fallback (zone deleted between pricing and
    # placement) snapshots from the option dict, which never carried dispatch_zone
    # — a blank dispatch zone in the table is that, not a bug.
    zone = models.JSONField(default=dict)
    cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    charged = models.DecimalField(max_digits=12, decimal_places=2)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "partner shipment"

    def __str__(self) -> str:
        return f"{self.order_id}: {self.partner.code} / {self.zone.get('lcda', '?')}"


class DeliveryBlock(TimeStampedModel):
    """Plan-41: "do not offer this delivery service HERE." Coverage is additive and
    this table is subtractive: a DeliveryOption covering all of Lagos cannot exclude
    one LGA, and GIG's coverage is synced from GIG rather than chosen — a block is
    the operator's veto over both. No rule = the service shows everywhere it already
    serves; a rule removes it from checkout at the matching addresses only.

    `service_code` is the Plan-41 service key (`services.service_code_for`): "gig",
    a partner's slug, "store_pickup", or "option:{pk}" for a manual option. A string,
    not an FK, because the services it can name live in three different tables.

    Granularity is the NARROWEST set level: `area_region` set → that LGA only; else
    `state_region` set → the whole state; else the whole `country_code`. Matching
    runs against the same ancestor closure the coverage matcher uses, so "block
    Lagos" catches every Lagos LGA exactly as "cover Lagos" offers to them.
    """

    service_code = models.CharField(max_length=40)
    # The RESOLVED market code (may be "ZZ" = Rest of World) — compared against
    # resolve_country() output, never the raw address ISO, so a DE address is caught
    # by a ZZ rule the same way it is served by ZZ options.
    country_code = models.CharField(max_length=2)
    state_region = models.ForeignKey(
        "core.Region", null=True, blank=True, on_delete=models.PROTECT,
        related_name="delivery_blocks_as_state", limit_choices_to={"level": "state"},
    )
    area_region = models.ForeignKey(
        "core.Region", null=True, blank=True, on_delete=models.PROTECT,
        related_name="delivery_blocks_as_area", limit_choices_to={"level": "area"},
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "delivery block"
        ordering = ["service_code", "country_code", "id"]

    def __str__(self) -> str:
        place = self.country_code
        if self.state_region_id:
            place += f"/{self.state_region.name}"
        if self.area_region_id:
            place += f"/{self.area_region.name}"
        suffix = "" if self.is_active else " (off)"
        return f"{self.service_code} blocked in {place}{suffix}"


class DeliveryFeeMask(TimeStampedModel):
    """Plan-41: a percentage added ON TOP of a service's real fee before the customer
    ever sees it — ₦5,000 masked at 10% displays and charges ₦5,500. One row per
    service, applied globally, kobo-exact.

    The mask never touches what the service costs US: GIG's raw quote stays in the
    quote cache and in `GigShipment.quote`/`cost`, so reconciliation still sees the
    true numbers — `charged − cost` includes exactly this markup.
    """

    service_code = models.CharField(max_length=40, unique=True)
    percent = models.DecimalField(max_digits=6, decimal_places=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "delivery fee mask"
        ordering = ["service_code"]

    def __str__(self) -> str:
        return f"{self.service_code} +{self.percent}% ({'on' if self.is_active else 'off'})"


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
