"""The delivery-partner portal API (Plan-39) — `/api/v1/partner/`.

A THIRD audience, not a variant of staff or customer: BrandnPack (and any future
no-API courier) logs in here with email + password and maintains their own rate card.
Edits go live at checkout immediately — Hammed's explicit ruling, no staff approval —
so the surface is kept exactly as small as that trust requires: one login, one
identity read, one LGA reference list, and CRUD over the partner's OWN zone rows.

Deliberately NOT under `/api/v1/admin/` (whose surface guard pins
`AdminJWTAuthentication` exactly) and never authenticated by anything but
`PartnerJWTAuthentication`: the audience equality check keeps partner tokens out of
the admin and customer surfaces, and `IsDeliveryPartner` re-reads the partner row's
`is_active` from the database on every request so the staff kill-switch revokes
access immediately, tokens outstanding or not.
"""
import logging

from django.contrib.auth import get_user_model
from rest_framework import exceptions, permissions, serializers, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import PartnerJWTAuthentication, mint_partner_token_pair
from apps.accounts.bff import require_bff_secret
from apps.accounts.throttling import PartnerLoginEmailThrottle, PartnerLoginIPThrottle
from apps.core.models import Region
from apps.delivery.models import PartnerZone

security_logger = logging.getLogger("apps.security")


class IsDeliveryPartner(permissions.BasePermission):
    """The DB-read half of the partner fence (the token's audience claim is the other).

    `getattr` with a default works because a reverse one-to-one miss raises
    `RelatedObjectDoesNotExist`, which subclasses AttributeError for exactly this use.
    """

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        partner = getattr(user, "delivery_partner", None)
        return bool(partner and partner.is_active)


class PartnerLoginView(APIView):
    """POST /api/v1/partner/auth/login/ — {email, password} → partner token pair.

    Same refusal discipline as the staff gate: every failure — unknown email, wrong
    password, an account with no partner profile, a partner switched off — answers
    with ONE generic 401, and the difference goes to the `apps.security` log. Saying
    more would make this endpoint an oracle for which addresses exist.

    Failure-counting throttles, IP first (see PartnerLoginIPThrottle), and the BFF
    shared-secret gate in front — the portal lives in the admin app's deployment, so
    the secret is already provisioned wherever this is legitimately called from.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # a login reads no credential but the body
    throttle_classes = [PartnerLoginIPThrottle, PartnerLoginEmailThrottle]
    log_throttling_at_error = True  # a capped partner gate is an alert, not a breadcrumb

    def get_authenticate_header(self, request) -> str:
        """Without this, DRF downgrades the AuthenticationFailed below to a 403 (no
        authenticator on the view means no WWW-Authenticate header, and RFC-shaped
        401s require one). SimpleJWT's own token views carry the same override."""
        return 'Bearer realm="api"'

    def post(self, request):
        email = ""
        raw = request.data.get("email") if hasattr(request.data, "get") else None
        if isinstance(raw, str):
            email = raw.strip().lower()
        password = request.data.get("password") if hasattr(request.data, "get") else None

        try:
            require_bff_secret(request)
            user = get_user_model().objects.filter(email__iexact=email).first() if email else None
            partner = getattr(user, "delivery_partner", None)
            ok = (
                user is not None
                and isinstance(password, str)
                and user.check_password(password)
                and user.is_active
                and partner is not None
                and partner.is_active
            )
            if not ok:
                raise exceptions.AuthenticationFailed(
                    "No active account found with the given credentials",
                    code="no_active_account",
                )
        except exceptions.APIException as exc:
            security_logger.error(
                "partner login failed for %s (%s)", email or "<no email>",
                exc.__class__.__name__,
            )
            if isinstance(exc, exceptions.AuthenticationFailed):
                # Only a submitted-and-rejected credential counts — same rule as the
                # staff gate, or junk POSTs become a zero-cost lockout of the partner.
                PartnerLoginEmailThrottle().record_failure(request)
                PartnerLoginIPThrottle().record_failure(request)
            raise
        security_logger.info("partner login succeeded for %s", email)
        PartnerLoginEmailThrottle().reset(request)
        PartnerLoginIPThrottle().reset(request)
        return Response({
            **mint_partner_token_pair(user),
            "partner": {"name": partner.name, "code": partner.code},
        })


class PartnerMeView(APIView):
    """GET /api/v1/partner/me/ — who am I, for the portal shell."""

    authentication_classes = [PartnerJWTAuthentication]
    permission_classes = [IsDeliveryPartner]

    def get(self, request):
        partner = request.user.delivery_partner
        return Response({
            "name": partner.name, "code": partner.code, "email": request.user.email,
        })


class PartnerLgaListView(APIView):
    """GET /api/v1/partner/lgas/ — the LGA dropdown for the rate-card form.

    Lagos only for now: BrandnPack's coverage is Lagos by their own doc, and offering
    all 774 Nigerian LGAs would make the dropdown a data-entry hazard. Widening this
    when a partner expands is a one-line filter change; the SERIALIZER's rule stays
    the looser "any NG area-level region" so no data migration is needed that day.
    """

    authentication_classes = [PartnerJWTAuthentication]
    permission_classes = [IsDeliveryPartner]

    def get(self, request):
        lagos = Region.objects.filter(country_code="NG", level="state", name="Lagos").first()
        regions = (
            Region.objects.filter(parent=lagos, level="area").order_by("name")
            if lagos else Region.objects.none()
        )
        return Response([{"id": r.id, "name": r.name} for r in regions])


class PublicRatesView(APIView):
    """GET /api/v1/partner/rates/ — every live rate card, for anybody.

    Hammed's marketers sell on the go and need to quote a delivery fee without a
    login; his ruling (2026-08-20) was a FULLY PUBLIC page showing the partner's raw
    fees. `AllowAny` follows the `ReferralTermsView` precedent: everything here is
    already disclosed to any guest by checkout itself (probe an LGA, read the
    BrandnPack option cards), so this endpoint discloses nothing new — it only saves
    the marketer 20 probes. Nothing about any person, ever.

    The filter is checkout's, exactly (`services.options_for_address`): active
    partner AND active zone AND a non-null price. A row this endpoint shows is a row
    a customer can buy right now — a marketer must never quote from a stale or
    staged rate, so the two surfaces must not be allowed to drift apart.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # anonymous by definition — a stale token must not 401 it

    def get(self, request):
        zones = (
            PartnerZone.objects.filter(
                partner__is_active=True, is_active=True, price__isnull=False,
            )
            .select_related("partner", "lga_region")
            .order_by("partner__name", "lga_region__name", "lcda_name")
        )
        cards: dict[int, dict] = {}
        for z in zones:
            card = cards.setdefault(z.partner_id, {
                "partner": z.partner.name, "code": z.partner.code, "zones": [],
            })
            card["zones"].append({
                # The pk is already public — checkout labels this row "pz:{id}".
                "id": z.id,
                "lga": z.lga_region.name,
                "lcda_name": z.lcda_name,
                "areas_covered": z.areas_covered,
                "dispatch_zone": z.dispatch_zone,
                "price": str(z.price),
                "min_days": z.min_days,
                "max_days": z.max_days,
            })
        return Response(list(cards.values()))


class PartnerZoneSerializer(serializers.ModelSerializer):
    """The five doc fields Hammed ruled the partner manages — LGA, LCDA, Major
    Locations & Landmarks, Dispatch Zone, Rate — plus the visibility switch.

    `price` floor of ₦1: with no approval step (edits go live immediately), a zero
    price would render as free delivery at checkout; a NULL price is the legitimate
    "not priced yet" state and stays allowed. The obvious remaining typo (₦400 for
    ₦4,000) is accepted risk under the same ruling — the storefront shows exactly
    what this table says.
    """

    lga_region = serializers.PrimaryKeyRelatedField(
        queryset=Region.objects.filter(country_code="NG", level="area")
    )
    lga_name = serializers.CharField(source="lga_region.name", read_only=True)
    price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=1, required=False, allow_null=True,
    )

    class Meta:
        model = PartnerZone
        fields = [
            "id", "lga_region", "lga_name", "lcda_name", "areas_covered",
            "dispatch_zone", "price", "is_active", "updated_at",
        ]
        read_only_fields = ["id", "lga_name", "updated_at"]
        extra_kwargs = {"dispatch_zone": {"required": False, "allow_blank": True}}


class PartnerZoneViewSet(viewsets.ModelViewSet):
    """CRUD over the caller's OWN rows — the partner FK comes from the token, never
    the payload, so one partner can neither read nor write another's card."""

    authentication_classes = [PartnerJWTAuthentication]
    permission_classes = [IsDeliveryPartner]
    serializer_class = PartnerZoneSerializer
    pagination_class = None  # one rate card, ~55 rows — the portal renders it whole

    def get_queryset(self):
        return (
            PartnerZone.objects.filter(partner=self.request.user.delivery_partner)
            .select_related("lga_region")
        )

    def perform_create(self, serializer):
        serializer.save(partner=self.request.user.delivery_partner)
