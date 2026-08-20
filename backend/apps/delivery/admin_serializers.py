"""Delivery option administration (Plan-19b).

FLAT FIELDS ONLY. Coverage (`countries`, `regions`) is read-only here and gets its own
screen in 19d, because editing it means choosing among 811 regions in a tree — a different
problem from "the Lagos price went up", which is the edit an operator actually makes month
to month as fuel and logistics costs move.

Weight tiers (`DeliveryOptionRate`) are deliberately absent: production has zero rows, and
a tier editor for an unpopulated table would be speculative UI.
"""
from decimal import Decimal

from django.db.models import Max
from rest_framework import serializers

from apps.core.models import Country, Region
from apps.delivery.models import DeliveryOption, GigShipment, SenderLocation

# The carriers checkout can actually quote and capture (apps/checkout/services/checkout.py
# branches on carrier_code). A "carrier" option naming anything else falls through to the
# flat-price path — and the carrier pattern sets price=0, so the customer would be offered
# free delivery. The API refuses it here rather than trusting every client.
KNOWN_CARRIERS = {"gig"}


def currency_mismatches(currency_id: str, countries, regions) -> list[str]:
    """Country codes in the given coverage whose selling currency differs from the
    option's. Checkout filters options to the order country's currency
    (`services.options_for_address`), so a mismatched option is not an error anywhere at
    runtime — it silently never appears. The only place that can catch it is the write."""
    codes = {c.code for c in countries} | {r.country_code.upper() for r in regions}
    return sorted(
        Country.objects.filter(code__in=codes)
        .exclude(currency_id=currency_id)
        .values_list("code", flat=True)
    )


class DeliveryOptionAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = (
        "name", "kind", "carrier_code", "price", "currency", "free_over",
        "quote_required", "disclaimer", "min_days", "max_days", "is_active", "sort",
        "country_codes", "region_ids",
    )

    # Writable ON CREATE ONLY, so the wizard makes an option and its coverage in one
    # request — no window where a coverage-less option sits active and matches nothing.
    # On update, `validate()` refuses them: coverage edits go through the `coverage`
    # action, so a price PATCH can never half-touch where an option is offered.
    country_codes = serializers.SlugRelatedField(
        source="countries", slug_field="code", many=True,
        queryset=Country.objects.all(), required=False,
    )
    region_count = serializers.IntegerField(source="regions.count", read_only=True)
    region_ids = serializers.PrimaryKeyRelatedField(
        source="regions", many=True, queryset=Region.objects.all(), required=False
    )
    coverage = serializers.SerializerMethodField()

    def get_coverage(self, obj) -> dict:
        """Structured coverage for the list's human summary line ("Ikeja + 1 more LGA,
        Lagos") — resolved server-side because the list page should not need all 879
        region rows just to name a handful. Region names are CAPPED; `region_total` is
        the honest count so the client can say "+ N more" instead of pretending the cap
        is everything. Needs the view to prefetch regions with select_related("parent")
        or this goes N+1."""
        regions = list(obj.regions.all())
        return {
            "countries": [{"code": c.code, "name": c.name} for c in obj.countries.all()],
            "regions": [
                {
                    "name": r.name,
                    "level": r.level,
                    "country_code": r.country_code,
                    "parent_name": r.parent.name if r.parent else None,
                }
                for r in regions[:6]
            ],
            "region_total": len(regions),
        }

    class Meta:
        model = DeliveryOption
        fields = [
            "id", "name", "kind", "carrier_code", "price", "currency", "free_over",
            "quote_required", "disclaimer", "min_days", "max_days", "is_active", "sort",
            "country_codes", "region_count", "region_ids", "coverage",
        ]

    def validate(self, attrs):
        """`min_days` above `max_days` renders as "3-1 days" on the storefront and reads
        as a bug in the shop rather than a typo in the admin."""
        errors: dict[str, str] = {}

        minimum = attrs.get("min_days", getattr(self.instance, "min_days", None))
        maximum = attrs.get("max_days", getattr(self.instance, "max_days", None))
        if minimum is not None and maximum is not None and minimum > maximum:
            errors["min_days"] = "The fastest estimate cannot be slower than the slowest."

        # Coverage is create-only here; edits go through the `coverage` action.
        if self.instance is not None and ("countries" in attrs or "regions" in attrs):
            errors["country_codes"] = (
                "Coverage cannot be edited here — use the coverage endpoint."
            )

        kind = attrs.get("kind", getattr(self.instance, "kind", "manual"))
        carrier = attrs.get("carrier_code", getattr(self.instance, "carrier_code", ""))
        if kind == "carrier" and carrier not in KNOWN_CARRIERS:
            errors["carrier_code"] = (
                "Checkout cannot quote this carrier. A carrier option it cannot quote "
                "is priced at its flat price instead — usually 0."
            )
        if kind == "manual" and carrier:
            errors["carrier_code"] = "A manual option does not name a carrier."

        # quote_required renders NO price at checkout — the disclaimer is the only text
        # the customer sees in its place. Without one, the option is a nameless blank.
        quote = attrs.get("quote_required", getattr(self.instance, "quote_required", False))
        disclaimer = attrs.get("disclaimer", getattr(self.instance, "disclaimer", ""))
        if quote and not (disclaimer or "").strip():
            errors["disclaimer"] = (
                'A "price quoted later" option needs the note shown instead of a price.'
            )

        if self.instance is None:
            countries = attrs.get("countries", [])
            regions = attrs.get("regions", [])
            if not countries and not regions:
                errors["country_codes"] = (
                    "Choose where this option is offered — an option covering nowhere "
                    "is never shown to anyone."
                )
            currency = attrs.get("currency")
            mismatched = currency_mismatches(
                getattr(currency, "code", currency), countries, regions
            )
            if currency is not None and mismatched:
                errors["currency"] = (
                    f"This option is priced in {getattr(currency, 'code', currency)} but "
                    f"covers {', '.join(mismatched)}, which sell in a different currency "
                    "— checkout would never show it there."
                )

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated_data):
        # New options join the END of the customer's list unless the caller says
        # otherwise: checkout orders by (sort, name) and the model default of 0 would
        # put every new option above the seeded ones (Lagos=1, GIG=5, Nationwide=10).
        if "sort" not in validated_data:
            top = DeliveryOption.objects.aggregate(m=Max("sort"))["m"] or 0
            validated_data["sort"] = top + 10
        return super().create(validated_data)


class DeliveryPartnerAdminSerializer(serializers.ModelSerializer):
    """Staff view of a partner (Plan-39): identity, the kill-switch, and the login
    email. The PASSWORD is deliberately not a field — it travels only through the
    dedicated `password/` action, which the audit allowlist here can never leak."""

    audit_allowlist = ("name", "is_active", "email")

    email = serializers.EmailField(source="user.email")
    zone_count = serializers.IntegerField(read_only=True)
    live_zone_count = serializers.IntegerField(read_only=True)
    has_password = serializers.SerializerMethodField()

    class Meta:
        from apps.delivery.models import DeliveryPartner

        model = DeliveryPartner
        fields = [
            "id", "name", "code", "email", "is_active",
            "zone_count", "live_zone_count", "has_password", "updated_at",
        ]
        read_only_fields = ["id", "code", "updated_at"]

    def get_has_password(self, obj) -> bool:
        """False until staff set real credentials — the seed migration creates the
        login with an UNUSABLE password, and the portal link is useless (and unsafe
        to share) before this flips."""
        return obj.user.has_usable_password()

    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", None)
        if user_data and "email" in user_data:
            instance.user.email = user_data["email"].lower()
            instance.user.save(update_fields=["email"])
        return super().update(instance, validated_data)


class PartnerZoneAdminSerializer(serializers.ModelSerializer):
    """Staff CRUD over partner rate-card rows (Plan-39) — the oversight half of a
    table the partner normally edits themselves: fix a typo'd rate, deactivate a row
    the moment a complaint lands, without waiting on the partner."""

    audit_allowlist = (
        "partner", "lga_region", "lcda_name", "areas_covered", "dispatch_zone",
        "price", "is_active",
    )

    lga_region = serializers.PrimaryKeyRelatedField(
        queryset=Region.objects.filter(country_code="NG", level="area")
    )
    lga_name = serializers.CharField(source="lga_region.name", read_only=True)
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    # Same ₦1 floor as the portal serializer: null = "not priced yet" is legitimate,
    # zero would sell free delivery.
    price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=1, required=False, allow_null=True,
    )

    class Meta:
        from apps.delivery.models import PartnerZone

        model = PartnerZone
        fields = [
            "id", "partner", "partner_name", "lga_region", "lga_name", "lcda_name",
            "areas_covered", "dispatch_zone", "price", "is_active", "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]


class RegionAdminSerializer(serializers.ModelSerializer):
    """A state or an area, flat. The TREE is assembled by the client from `parent` —
    811 rows for Nigeria is one small response, and shipping it whole beats 37 requests
    to expand each state."""

    audit_allowlist = ("name", "is_active")

    class Meta:
        from apps.core.models import Region

        model = Region
        fields = ["id", "country_code", "name", "level", "parent", "is_active"]


class DeliveryCoverageSerializer(serializers.Serializer):
    """The coverage write, kept apart from the flat-field serializer on purpose.

    Coverage is MIXED GRANULARITY (master spec Decision 13): an option can serve whole
    countries, whole states, or individual areas, in any combination. Putting that on the
    same PATCH as `price` would mean an operator editing a price could silently clear
    every region if their client omitted the key — the exact class of accident that makes
    "why did Lagos stop being served?" unanswerable.
    """

    audit_allowlist = ("country_codes", "region_ids")

    country_codes = serializers.ListField(child=serializers.CharField(), required=False)
    region_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class _ServiceNameMixin:
    """Resolves `service_code` to its human label through the same canonical list the
    picker endpoint serves — cached on the serializer instance, so a list render costs
    one pass over the services, not one per row (many=True shares the child)."""

    def _service_names(self) -> dict:
        if not hasattr(self, "_service_name_cache"):
            from apps.delivery.services import known_delivery_services

            self._service_name_cache = {
                s["code"]: s["name"] for s in known_delivery_services()
            }
        return self._service_name_cache

    def get_service_name(self, obj) -> str:
        # A code that no longer resolves (a deleted manual option) falls back to the
        # raw code — the rule stays visible and deletable rather than unlabelled.
        return self._service_names().get(obj.service_code, obj.service_code)

    def validate_service_code(self, value):
        if value not in self._service_names():
            raise serializers.ValidationError(
                "Unknown delivery service — pick one from the list."
            )
        return value


class DeliveryBlockAdminSerializer(_ServiceNameMixin, serializers.ModelSerializer):
    """One Plan-41 block rule. The three place fields cascade: country alone blocks
    the whole country, + state narrows to the state, + LGA narrows to the LGA. The
    write refuses geographically impossible combinations here — checkout would not
    error on them, it would just silently never match, which is worse."""

    audit_allowlist = (
        "service_code", "country_code", "state_region", "area_region", "is_active",
    )

    service_name = serializers.SerializerMethodField()
    state_region = serializers.PrimaryKeyRelatedField(
        queryset=Region.objects.filter(level="state"), required=False, allow_null=True
    )
    area_region = serializers.PrimaryKeyRelatedField(
        queryset=Region.objects.filter(level="area"), required=False, allow_null=True
    )
    state_name = serializers.SerializerMethodField()
    area_name = serializers.SerializerMethodField()

    class Meta:
        from apps.delivery.models import DeliveryBlock

        model = DeliveryBlock
        fields = [
            "id", "service_code", "service_name", "country_code",
            "state_region", "state_name", "area_region", "area_name",
            "is_active", "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]

    def get_state_name(self, obj):
        return obj.state_region.name if obj.state_region_id else None

    def get_area_name(self, obj):
        return obj.area_region.name if obj.area_region_id else None

    def validate_country_code(self, value):
        value = (value or "").upper()
        if not Country.objects.filter(code=value).exists():
            raise serializers.ValidationError(
                "Unknown country — use a market code from the country list."
            )
        return value

    def validate(self, attrs):
        country = attrs.get(
            "country_code", getattr(self.instance, "country_code", "")
        ).upper()
        state = attrs.get("state_region", getattr(self.instance, "state_region", None))
        area = attrs.get("area_region", getattr(self.instance, "area_region", None))

        errors: dict[str, str] = {}
        if state is not None and state.country_code.upper() != country:
            errors["state_region"] = "That state is not in the chosen country."
        if area is not None:
            if state is None:
                errors["area_region"] = "Pick the state first — an LGA block needs its state."
            else:
                node, inside = area.parent, False
                while node is not None:
                    if node.id == state.id:
                        inside = True
                        break
                    node = node.parent
                if not inside:
                    errors["area_region"] = "That LGA is not in the chosen state."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class DeliveryFeeMaskAdminSerializer(_ServiceNameMixin, serializers.ModelSerializer):
    """One Plan-41 fee mask: service + the percentage added on top of its real fee.
    The 400% ceiling is a typo guard (\"110\" for \"10\"), not a policy position."""

    audit_allowlist = ("service_code", "percent", "is_active")

    service_name = serializers.SerializerMethodField()
    percent = serializers.DecimalField(
        max_digits=6, decimal_places=2,
        min_value=Decimal("0"), max_value=Decimal("400"),
    )

    class Meta:
        from apps.delivery.models import DeliveryFeeMask

        model = DeliveryFeeMask
        fields = ["id", "service_code", "service_name", "percent", "is_active", "updated_at"]
        read_only_fields = ["id", "updated_at"]


class GigShipmentRowSerializer(serializers.ModelSerializer):
    """One row of the deliveries table (Plan-35) — READ ONLY, composed entirely from
    snapshots the shipment and its order already hold, so a page of rows costs one
    query and zero HTTP. The origin/centre/address snapshots are the source, not the
    live tables: this list answers "what happened", and history must not shift when
    a location is renamed or a centre closes.
    """

    order_number = serializers.CharField(source="order.number", read_only=True)
    placed_at = serializers.DateTimeField(source="order.placed_at", read_only=True)
    currency = serializers.CharField(source="order.currency_id", read_only=True)
    origin = serializers.SerializerMethodField()
    service = serializers.SerializerMethodField()
    destination = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()

    class Meta:
        model = GigShipment
        fields = [
            "order_number", "placed_at", "status", "waybill", "origin", "service",
            "destination", "customer_name", "customer_phone", "charged", "cost",
            "currency", "last_scan", "last_tracked_at",
        ]

    def get_origin(self, obj) -> dict:
        """An empty snapshot means pre-Plan-34 or the env fallback — labelled as the
        built-in origin (id 0) so old shipments stay legible and filterable, never
        resolved against today's settings (which may have moved since)."""
        if obj.origin:
            return {"id": obj.origin.get("id", 0), "name": obj.origin.get("name", "")}
        return {"id": 0, "name": "Ogudu (built-in)"}

    def get_service(self, obj) -> str:
        return "pickup" if obj.centre else "door"

    def get_destination(self, obj) -> str:
        if obj.centre:
            return obj.centre.get("name", "")
        addr = obj.order.shipping_address or {}
        return ", ".join(p for p in (addr.get("area"), addr.get("state")) if p)

    def get_customer_name(self, obj) -> str:
        addr = obj.order.shipping_address or {}
        return " ".join(p for p in (addr.get("first_name"), addr.get("last_name")) if p)

    def get_customer_phone(self, obj) -> str:
        return (obj.order.shipping_address or {}).get("phone", "")


class SenderLocationAdminSerializer(serializers.ModelSerializer):
    """Plan-34: one Toke fulfilment point GIG collects from. The pin prices every
    quote and is where the rider drives; the phone is who GIG calls to coordinate
    the pickup — both are validated hard, not trusted."""

    audit_allowlist = (
        "name", "phone", "address", "locality", "latitude", "longitude",
        "state", "lga", "customer_pickup", "state_region", "is_active",
    )

    # DISPLAY ONLY (Plan-35): filing labels for the pickup-locations page. Nothing
    # routes on them for GIG — the pin is the only GIG routing input. Customer store
    # pickup (Plan-40) routes on `state_region` below, never on this text.
    state = serializers.CharField(
        required=False, allow_blank=True, max_length=100,
        help_text="Display label — GIG routing follows the pin, never this.",
    )
    lga = serializers.CharField(
        required=False, allow_blank=True, max_length=100,
        help_text="Display label — GIG routing follows the pin, never this.",
    )
    # Plan-40: the canonical state this row shows under when it is a customer pickup
    # store. Constrained to level="state" in the queryset, not just prose — an LGA id
    # pasted here must 400, or a store silently matches nobody.
    state_region = serializers.PrimaryKeyRelatedField(
        queryset=Region.objects.filter(level="state"),
        required=False, allow_null=True,
        help_text="Canonical state — customer store pickup matches on this.",
    )
    customer_pickup = serializers.BooleanField(
        required=False, default=False,
        help_text="Offer this location to customers as a ₦0 pickup store.",
    )

    class Meta:
        model = SenderLocation
        fields = [
            "id", "name", "phone", "address", "locality",
            "latitude", "longitude", "state", "lga",
            "customer_pickup", "state_region", "is_active", "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]

    def validate(self, attrs):
        """A customer-facing store with no canonical state matches NO customer and
        renders NOWHERE — refuse the save rather than let the flag silently do
        nothing. Reads the instance for PATCHes that touch only one of the pair."""
        customer_pickup = attrs.get(
            "customer_pickup",
            self.instance.customer_pickup if self.instance else False,
        )
        state_region = attrs.get(
            "state_region",
            self.instance.state_region if self.instance else None,
        )
        if customer_pickup and state_region is None:
            raise serializers.ValidationError({
                "state_region": "Pick the store's state — customers are matched by state.",
            })
        # Keep the display label in step with the canonical pick, so the list row and
        # the storefront never disagree about what state a store is in.
        if state_region is not None and not attrs.get("state"):
            attrs["state"] = state_region.name
        return attrs

    def validate_phone(self, value):
        from apps.core.phones import normalize_e164

        try:
            normalized = normalize_e164(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        if not normalized:
            raise serializers.ValidationError(
                "A pickup phone is required — GIG calls it to coordinate the collection."
            )
        return normalized

    def validate_latitude(self, value):
        if not 4 <= value <= 14:
            raise serializers.ValidationError(
                "Latitude must be inside Nigeria (4–14). Right-click the spot in "
                "Google Maps and copy the first number."
            )
        return value

    def validate_longitude(self, value):
        if not Decimal("2.5") <= value <= 15:
            raise serializers.ValidationError(
                "Longitude must be inside Nigeria (2.5–15). Right-click the spot in "
                "Google Maps and copy the second number."
            )
        return value
