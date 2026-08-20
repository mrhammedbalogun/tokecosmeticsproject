"""Delivery admin (Plan-19b).

`products.manage`, matching inventory's reasoning: a Manager runs the shop day to day and
a delivery price is an operational number, not a money-routing decision like the payout
account (which is Owner-only under `settings.manage`).
"""
from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, viewsets

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.core.audit import AdminAuditMixin
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from apps.core.models import Country, Region
from apps.delivery.admin_serializers import (
    DeliveryCoverageSerializer,
    DeliveryOptionAdminSerializer,
    DeliveryPartnerAdminSerializer,
    GigShipmentRowSerializer,
    PartnerZoneAdminSerializer,
    SenderLocationAdminSerializer,
    RegionAdminSerializer,
    currency_mismatches,
)
from apps.delivery.models import DeliveryOption, SenderLocation


class DeliveryOptionAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """Full CRUD. Delete became real when creation did (the wizard): a mistyped option
    deserves better than immortality as an inactive row. It is referentially safe —
    orders snapshot only the option NAME (`Order.delivery_option_name`), nothing holds
    an FK to the row, and a checkout in flight re-matches by id at place time, where a
    deleted option fails exactly like a deactivated one. "Retire because prices moved"
    is still `is_active=False`; delete is for mistakes.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    serializer_class = DeliveryOptionAdminSerializer
    audit_serializers = (DeliveryOptionAdminSerializer,)
    queryset = (
        DeliveryOption.objects.select_related("currency")
        .prefetch_related(
            "countries",
            # parent joined so the coverage summary can say "Ikeja, Lagos" without an
            # extra query per region row.
            Prefetch("regions", queryset=Region.objects.select_related("parent")),
        )
        .order_by("sort", "name")
    )
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["is_active", "kind", "countries"]
    # No pagination: the global PAGE_SIZE (24) would silently truncate the list page
    # at option 25, and under country grouping a truncated list reads as "this country
    # has no options" — a lie with consequences. The row count here is operator-scale.
    pagination_class = None

    def destroy(self, request, *args, **kwargs):
        # `changes` is normally built from request.data — empty on a DELETE. And a
        # seeded option has no API create row either, so without this snapshot the
        # audit trail would prove only that *something* was deleted. Serialized BEFORE
        # the delete, merged into the row by `_changes` below, same transaction.
        self._deleted_option = DeliveryOptionAdminSerializer(self.get_object()).data
        return super().destroy(request, *args, **kwargs)

    def _changes(self, response) -> dict:
        changes = super()._changes(response)
        if self.request.method.upper() == "DELETE" and hasattr(self, "_deleted_option"):
            changes["deleted"] = self._deleted_option
        return changes

    @action(detail=False, methods=["get"])
    def preview(self, request):
        """`GET /admin/delivery-options/preview/?country=NG&state_region=1&area_region=2`

        "What would a customer HERE be offered?" answered by the real matcher
        (`services.options_for_address`), not a client-side mirror — the mirror can
        only ever drift. Prices are computed on an empty cart (no weight tiers, no
        free-over), and `kind="carrier"` options are returned WITHOUT calling the
        carrier: the admin wants coverage truth, not a live GIG quote per keystroke.
        """
        from decimal import Decimal
        from types import SimpleNamespace

        from apps.core.country_context import resolve_country
        from apps.delivery.services import options_for_address

        code = (request.query_params.get("country") or "").upper()
        country = resolve_country(code)
        if country is None:
            return Response({"country": ["Unknown country code."]}, status=400)

        def region_or_400(param):
            raw = request.query_params.get(param)
            if not raw:
                return None
            region = Region.objects.filter(id=raw).first()
            if region is None:
                raise ValueError(param)
            return region

        try:
            address = SimpleNamespace(
                country_code=code,
                state_region=region_or_400("state_region"),
                area_region=region_or_400("area_region"),
            )
        except ValueError as exc:
            return Response({str(exc): ["Unknown region id."]}, status=400)

        options = options_for_address(address, [], Decimal("0"), country)
        return Response({"country": country.code, "options": options})

    @action(detail=True, methods=["put"])
    def coverage(self, request, pk=None):
        """`PUT /admin/delivery-options/{id}/coverage/` — Plan-19d.

        A REPLACE, not a merge, and its own endpoint rather than a field on the flat
        serializer. Coverage is mixed granularity (whole countries, whole states,
        individual areas), and folding it into the price PATCH would let a client that
        omitted the key silently clear every region.
        """
        option = self.get_object()
        serializer = DeliveryCoverageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        codes = serializer.validated_data.get("country_codes")
        countries = Country.objects.filter(code__in=codes) if codes is not None else None
        region_ids = serializer.validated_data.get("region_ids")
        regions = Region.objects.filter(id__in=region_ids) if region_ids is not None else None

        # Same rule the create path enforces: coverage in a currency the option is not
        # priced in silently never appears at checkout (services.options_for_address
        # filters on the order currency), so the write is the only place to catch it.
        mismatched = currency_mismatches(
            option.currency_id,
            countries if countries is not None else option.countries.all(),
            regions if regions is not None else option.regions.all(),
        )
        if mismatched:
            return Response(
                {"country_codes": [
                    f"This option is priced in {option.currency_id} but this coverage "
                    f"includes {', '.join(mismatched)}, which sell in a different "
                    "currency — checkout would never show it there."
                ]},
                status=400,
            )

        if countries is not None:
            option.countries.set(countries)
        if regions is not None:
            option.regions.set(regions)

        option.refresh_from_db()
        return Response(DeliveryOptionAdminSerializer(option).data, status=200)


class RegionAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """The regions browser (Plan-19d). Read plus `is_active`, nothing else.

    NO CREATE OR DELETE. The 811 rows are reference data seeded by migration — Nigeria's
    37 states and 774 LGAs are not a thing an operator invents, and a typo'd extra "Lagos"
    would silently never match an address. Deactivating is how a place stops being
    offered.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    serializer_class = RegionAdminSerializer
    audit_serializers = (RegionAdminSerializer,)
    audit_model_label = "core.region"
    queryset = Region.objects.all().order_by("country_code", "level", "name")
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["country_code", "level", "is_active", "parent"]
    pagination_class = None  # 811 rows is one response; the client builds the tree
    http_method_names = ["get", "patch", "head", "options"]


class SenderLocationAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """Pickup origins (Plan-34): the Toke locations GIG collects from. Same scope
    reasoning as delivery options — an operational number, `products.manage`.

    Delete is refused once any shipment's origin snapshot references the row:
    the snapshot answers history on its own, but reusing a freed pk would let a
    NEW row silently inherit an old shipment's identity in the audit trail.
    "This shop closed" is `is_active=False`; delete is for typos that never
    shipped anything. Deactivating every row is safe by construction — selection
    falls back to the `GIG_SENDER_*` env origin, it never breaks a checkout.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    serializer_class = SenderLocationAdminSerializer
    audit_serializers = (SenderLocationAdminSerializer,)
    queryset = SenderLocation.objects.order_by("name")
    pagination_class = None  # operator-scale rows, same reasoning as delivery options

    def destroy(self, request, *args, **kwargs):
        from apps.delivery.models import GigShipment

        row = self.get_object()
        if GigShipment.objects.filter(origin__id=row.pk).exists():
            return Response(
                {"detail": "Shipments were quoted from this location — deactivate it "
                           "instead of deleting."},
                status=400,
            )
        self._deleted_origin = SenderLocationAdminSerializer(row).data
        return super().destroy(request, *args, **kwargs)

    def _changes(self, response) -> dict:
        changes = super()._changes(response)
        if self.request.method.upper() == "DELETE" and hasattr(self, "_deleted_origin"):
            changes["deleted"] = self._deleted_origin
        return changes


class DeliveryPartnerAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """Delivery partners (Plan-39): the kill-switch, the login email, and the
    `password/` action. `settings.manage` (Owner-only), NOT `products.manage` like the
    rest of this file: setting a partner's password mints a credential for an external
    business whose edits land straight at checkout — that is closer to staff.manage's
    "invites mint administrators" reasoning than to editing a delivery price.

    NO CREATE OR DELETE. A partner arrives via migration/shell (it needs a user row
    and a portal onboarding conversation, not a form), and delete would orphan the
    login and the zones — "the partnership ended" is `is_active=False`.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("settings.manage")]
    serializer_class = DeliveryPartnerAdminSerializer
    audit_serializers = (DeliveryPartnerAdminSerializer,)
    pagination_class = None
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        from django.db.models import Count, Q

        from apps.delivery.models import DeliveryPartner

        return (
            DeliveryPartner.objects.select_related("user")
            .annotate(
                zone_count=Count("zones"),
                live_zone_count=Count(
                    "zones", filter=Q(zones__is_active=True, zones__price__isnull=False)
                ),
            )
            .order_by("name")
        )

    def create(self, request, *args, **kwargs):
        # http_method_names allows POST for the password action below; the router
        # also maps a bare POST to create, which must stay closed.
        return Response({"detail": "Partners are provisioned by migration, not API."},
                        status=405)

    @action(detail=True, methods=["post"])
    def password(self, request, pk=None):
        """POST /admin/partners/{id}/password/ {"password": "..."} — set the portal
        login password. Validated through the project's AUTH_PASSWORD_VALIDATORS
        (same bar as staff/customer passwords); the value itself never reaches the
        audit row — the serializer allowlist has no password field, and this action
        records only that the reset happened."""
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError

        partner = self.get_object()
        password = request.data.get("password")
        if not isinstance(password, str) or not password:
            return Response({"password": ["A password is required."]}, status=400)
        try:
            validate_password(password, user=partner.user)
        except DjangoValidationError as exc:
            return Response({"password": exc.messages}, status=400)
        partner.user.set_password(password)
        partner.user.save(update_fields=["password"])
        return Response({"ok": True})

    def _changes(self, response) -> dict:
        # The password action's request body must never reach the audit trail.
        if getattr(self, "action", "") == "password":
            return {"password_set": True}
        return super()._changes(response)


class PartnerZoneAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """Partner rate-card rows, staff side (Plan-39). `products.manage`, same reasoning
    as delivery options: a delivery price is an operational number. Delete is
    referentially safe for the same reason option delete is — orders snapshot only
    the composed option name, and an in-flight checkout re-matches at place time,
    where a deleted zone fails exactly like a deactivated one."""

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    serializer_class = PartnerZoneAdminSerializer
    audit_serializers = (PartnerZoneAdminSerializer,)
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["partner", "lga_region", "is_active"]
    pagination_class = None  # one partner's card is ~55 rows; truncation would lie

    def get_queryset(self):
        from apps.delivery.models import PartnerZone

        return PartnerZone.objects.select_related("partner", "lga_region").order_by(
            "lga_region__name", "lcda_name"
        )

    def destroy(self, request, *args, **kwargs):
        self._deleted_zone = PartnerZoneAdminSerializer(self.get_object()).data
        return super().destroy(request, *args, **kwargs)

    def _changes(self, response) -> dict:
        changes = super()._changes(response)
        if self.request.method.upper() == "DELETE" and hasattr(self, "_deleted_zone"):
            changes["deleted"] = self._deleted_zone
        return changes


class AdminGigShipmentListView(AdminAuditMixin, generics.ListAPIView):
    """GET /api/v1/admin/gig-shipments/ — the deliveries table (Plan-35): every GIG
    shipment with its origin, destination, customer and money columns, newest first.
    The packing-desk question it exists to answer: "what must MY shop pack today?"
    (filter by origin).

    `orders.view` and READ-AUDITED, the order-list posture exactly: every row names a
    customer and their phone. Paginated — this table grows with every order, and an
    unpaginated dump would be bulk PII egress in one call (the CSV precedent gates
    that at `orders.manage`; no export exists here on purpose).

    The table READS; the order page ACTS (plan ruling 4): no capture or label
    endpoints hang off this route — rows link to the order, where the confirm
    ritual lives.

    Filters: `status`, `origin` (snapshot id; 0 matches BOTH id-0 snapshots and the
    empty pre-Plan-34 dict, so history never vanishes from a filtered view),
    `service` (door|pickup, resolved from the centre snapshot), `placed_after`/
    `placed_before` (the order's placed date).
    """

    serializer_class = GigShipmentRowSerializer
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.view")]
    audit_reads = True
    audit_action = "list"

    def get_queryset(self):
        from django.db.models import Q

        from apps.delivery.models import GigShipment

        qs = GigShipment.objects.select_related("order")
        p = self.request.query_params
        if v := p.get("status"):
            qs = qs.filter(status=v)
        if (v := p.get("origin")) is not None and v != "":
            try:
                origin_id = int(v)
            except ValueError:
                return qs.none()  # a non-numeric id matches no origin, honestly
            if origin_id == 0:
                # id 0 ≡ the empty pre-Plan-34 snapshot — both are the built-in
                # origin, and old shipments must not vanish from a filtered view.
                qs = qs.filter(Q(origin={}) | Q(origin__id=0))
            else:
                qs = qs.filter(origin__id=origin_id)
        if v := p.get("service"):
            if v == "pickup":
                qs = qs.exclude(centre={})
            elif v == "door":
                qs = qs.filter(centre={})
        # Dates are parsed eagerly: a lazy-filtered garbage value would 500 at
        # evaluation time, deep in pagination. Unparseable cutoff = no matches.
        from django.utils.dateparse import parse_date, parse_datetime

        for param, lookup in (("placed_after", "gte"), ("placed_before", "lte")):
            if v := p.get(param):
                parsed = parse_datetime(v) or parse_date(v)
                if parsed is None:
                    return qs.none()
                qs = qs.filter(**{f"order__placed_at__{lookup}": parsed})
        return qs.order_by("-order__placed_at", "-pk")


class AdminGigShipmentView(AdminAuditMixin, APIView):
    """GET /api/v1/admin/orders/{number}/gig/ — the fulfilment panel's data: the
    shipment, the cached wallet balance, and whether capture is currently legal
    (with the reason when it isn't, so the UI renders a sentence, not a grey box).

    `orders.view` and read-audited: the payload carries the receiver snapshot's
    order linkage — same PII posture as the order detail it sits beside.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.view")]
    audit_reads = True
    audit_action = "read"
    audit_model_label = "delivery.gigshipment"

    def get(self, request, number: str):
        from django.core.cache import cache as django_cache

        from apps.delivery.gig.capture import WALLET_CACHE_KEY
        from apps.delivery.models import GigShipment
        from apps.orders.models import Order

        order = get_object_or_404(Order, number=number)
        shipment = GigShipment.objects.filter(order=order).first()
        if shipment is None:
            return Response({"shipment": None})

        can_capture, reason = True, ""
        if shipment.status != "quoted":
            can_capture, reason = False, f"shipment is {shipment.status}"
        elif order.status != "processing":
            can_capture, reason = False, f"order is {order.status} — capture after payment"

        raw_balance = django_cache.get(WALLET_CACHE_KEY)
        return Response({
            "shipment": {
                "status": shipment.status,
                "waybill": shipment.waybill,
                "cost": str(shipment.cost) if shipment.cost is not None else None,
                "charged": str(shipment.charged),
                "quote": shipment.quote,
                "label_url": shipment.label_url,
                "capture_api_id": shipment.capture_api_id,
                "last_scan": shipment.last_scan,
                "last_tracked_at": shipment.last_tracked_at,
                # Centre-pickup snapshot (32b slice 5): {} for door shipments. The
                # packing desk needs to see WHERE the parcel is routed before pressing
                # the button that debits the wallet.
                "centre": shipment.centre,
                # Sender-origin snapshot (Plan-34): {} = the env origin. The desk
                # must see WHICH shop the rider is being sent to before the button
                # that dispatches one — an Ogudu packer must never capture an
                # Abuja-routed shipment.
                "origin": shipment.origin,
            },
            # "unknown" is honest: the sandbox account has no wallet record, and a
            # stale/absent cache is not a zero.
            "wallet_balance": None if raw_balance in (None, "unknown") else raw_balance,
            "can_capture": can_capture,
            "capture_blocked_reason": reason,
        })


class AdminGigCaptureView(AdminAuditMixin, APIView):
    """POST /api/v1/admin/orders/{number}/gig/capture/ — create the waybill.

    `orders.manage`, the money-touching scope: this call debits the GIG wallet
    the full GrandTotal and dispatches a rider, irrevocably. The service refuses
    ineligible states and insufficient balance BEFORE calling GIG; a timeout
    parks the shipment in `create_unconfirmed` and this endpoint answers 502
    with the instruction to check with GIG — never an automatic retry.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.manage")]
    audit_action = "gig_capture"
    audit_model_label = "delivery.gigshipment"

    def post(self, request, number: str):
        from apps.delivery.gig.capture import CaptureRefused, CaptureUnconfirmed, capture_shipment
        from apps.delivery.gig.client import GigError
        from apps.orders.models import Order

        order = get_object_or_404(Order, number=number)
        try:
            shipment = capture_shipment(order, actor=request.user)
        except CaptureRefused as exc:
            return Response({"error": exc.code, "detail": exc.detail}, status=409)
        except CaptureUnconfirmed:
            return Response(
                {"error": "capture_unconfirmed",
                 "detail": "The capture timed out — GIG may have created a waybill and "
                           "debited the wallet. Check with GIG (WhatsApp) before ANY retry."},
                status=502,
            )
        except GigError as exc:
            return Response(
                {"error": "gig_rejected", "detail": str(exc), "api_id": exc.api_id}, status=502
            )
        return Response({"waybill": shipment.waybill, "cost": str(shipment.cost)})


class AdminGigLabelView(AdminAuditMixin, APIView):
    """POST /api/v1/admin/orders/{number}/gig/label/ — fetch the waybill label PDF.

    `orders.operate`: printing a label is packing-bench work. "Not ready yet" is a
    NORMAL answer (GIG generates the label only after the parcel passes through
    their station), rendered as 200 + ready:false so the UI shows a sentence and
    a retry button rather than an error state.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.operate")]
    audit_action = "gig_label"
    audit_model_label = "delivery.gigshipment"

    def post(self, request, number: str):
        from apps.delivery.gig.capture import CaptureRefused, fetch_label
        from apps.delivery.gig.client import GigUnavailable
        from apps.delivery.models import GigShipment
        from apps.orders.models import Order

        order = get_object_or_404(Order, number=number)
        shipment = get_object_or_404(GigShipment, order=order)
        try:
            url = fetch_label(shipment)
        except CaptureRefused as exc:
            return Response({"error": exc.code, "detail": exc.detail}, status=409)
        except GigUnavailable as exc:
            return Response({"error": "gig_unreachable", "detail": str(exc)}, status=502)
        if url is None:
            return Response({"ready": False,
                             "detail": "Label not generated yet — GIG produces it after the "
                                       "parcel is processed at their station."})
        return Response({"ready": True, "label_url": url})
