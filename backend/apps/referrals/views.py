"""The customer's own referral endpoints, under /api/v1/me/referrals/.

Thin by design: every rule lives in `services`, and these views translate HTTP. The one
piece of judgement they hold is which shape goes on the wire, and that is in
`serializers`.

Everything here is `IsAuthenticated` and scoped to `request.user` in the QUERY, never
filtered after the fetch — the difference matters on the payout endpoints, where an
object-level check applied late is one refactor away from being applied never.
"""
from __future__ import annotations

from django.conf import settings
from rest_framework import permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.throttling import PayoutMethodWriteThrottle, ReferralLookupThrottle
from apps.core.models import Currency
from apps.referrals import services
from apps.referrals.models import (
    Commission,
    PayoutMethod,
    PayoutRequest,
    ReferralAdjustment,
    ReferralProfile,
)
from apps.payments.money import format_money
from apps.referrals.serializers import (
    AdjustmentSerializer,
    club_name,
    CommissionSerializer,
    PayoutCreateSerializer,
    PayoutMethodSerializer,
    PayoutMethodWriteSerializer,
    PayoutRequestSerializer,
    TierSerializer,
    WalletSerializer,
)


class _Page(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _referral_error(exc: services.ReferralError) -> Response:
    """One translation of the service's refusals into HTTP, used by every writer here.

    The body carries a stable `error` code alongside the human `detail` so the
    storefront can special-case the two refusals that need their own UI (terms not yet
    accepted; no payout account saved) without string-matching English.
    """
    return Response({"error": exc.code, "detail": exc.detail}, status=exc.http)


class ReferralOverviewView(APIView):
    """GET /api/v1/me/referrals/ — everything the account page's hero needs, in one call.

    Deliberately one endpoint rather than four: this page is a dashboard, every widget
    on it is above the fold, and four round-trips through the BFF to render one screen
    is four chances for a partial render.

    This is also the endpoint that CREATES the referral profile, via `ensure_profile` —
    see that function for why the programme has no signup and no signal.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = services.ensure_profile(request.user)
        wallets = services.balances(request.user)
        return Response({
            "code": profile.code,
            "is_blocked": profile.is_blocked,
            "terms_accepted_at": profile.terms_accepted_at,
            "terms_version": profile.terms_version,
            "current_terms_version": settings.REFERRAL_TERMS_VERSION,
            "share_url": _share_url(profile.code),
            # Published as data rather than baked into the storefront copy: the page
            # tells the customer "10%", "30 days", "60 days", and those three numbers
            # ARE the settings. A hardcoded "10%" in JSX is a promise that silently
            # stops matching the code that pays it.
            "commission_percent": str(settings.REFERRAL_COMMISSION_PERCENT),
            "cookie_days": settings.REFERRAL_COOKIE_DAYS,
            "hold_days": settings.REFERRAL_HOLD_DAYS,
            "referred_customers": services.referred_customer_count(request.user),
            "wallets": WalletSerializer(wallets, many=True).data,
            "tiers": TierSerializer(services.tier_progress(request.user), many=True).data,
            "has_payout_method": PayoutMethod.objects.filter(user=request.user).exists(),
        })


def _share_url(code: str) -> str:
    """The link a referrer shares. Built server-side so the code, the parameter name and
    the storefront origin agree in exactly one place; the storefront's proxy reads the
    same parameter name (`ref`) and nothing else."""
    return f"{settings.FRONTEND_URL.rstrip('/')}/?ref={code}"


class ReferralCodeLookupView(APIView):
    """GET /api/v1/referrals/lookup/?code=X — "is this a real code, and whose?"

    THE ONLY PUBLIC ENDPOINT IN THIS APP, and it exists so a bare code is usable at all.
    The programme is link-first (`?ref=`), but people share codes in captions, voice
    notes and over the phone, and until this landed the share card advertised a code that
    nothing could redeem.

    ── WHAT IT DISCLOSES, AND WHY THAT IS ACCEPTABLE ───────────────────────────────

    A first name, for a code that is designed to be published. That is the whole point:
    "✓ You're shopping with Amina's link" is what tells someone they typed it correctly,
    and without it the field is a black box. No email, no surname, no totals, no
    indication of whether the referrer has ever earned anything.

    It is still an enumeration surface — guess codes, harvest first names — so it is
    throttled. The cap is a junk-volume cap rather than a guess cap: a guessed code
    credits a stranger with commission, which costs that stranger nothing and the shop
    nothing beyond noise, so the threat does not justify a tighter limit that would
    catch real customers. Note the shared-bucket caveat in `accounts.throttling`: the
    storefront reaches this through the BFF, so all customers share one IP bucket.

    ── SELF-REFERRAL IS ANSWERED HERE, NOT SWALLOWED ──────────────────────────────

    `attribution_code_for_order` silently drops a self-referral at order time, which is
    right for a cookie the customer never chose. But somebody who TYPES their own code
    and is told "✓ You're shopping with Amina's link" — their own name — would reasonably
    expect to be paid. So an authenticated caller applying their own code is refused
    explicitly. This leaks nothing: they already know their own code.
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ReferralLookupThrottle]

    def get(self, request):
        code = (request.query_params.get("code") or "").strip().upper()
        if not code:
            return Response({"valid": False, "reason": "empty"})

        profile = (
            ReferralProfile.objects.select_related("user")
            .filter(code__iexact=code, is_blocked=False)
            .first()
        )
        if profile is None:
            # Blocked and non-existent are the same answer on purpose: "that code is
            # suspended" tells an abuser their block landed.
            return Response({"valid": False, "reason": "not_found"})

        user = request.user
        if getattr(user, "is_authenticated", False) and profile.user_id == user.pk:
            return Response({"valid": False, "reason": "self"})

        return Response({
            "valid": True,
            # First name only, and never the email. "A friend" for an account with no
            # name on it, so the confirmation line always reads as a sentence.
            "referrer_name": profile.user.first_name.strip() or "a friend",
        })


class ReferralTermsView(APIView):
    """GET /api/v1/referrals/terms/ — the programme's published numbers, for anybody.

    ── WHY A PUBLIC ENDPOINT AND NOT A CONSTANT IN THE STOREFRONT ──────────────────

    `/affiliates` is a MARKETING page: it tells the world "10% of every sale", "30-day
    window", "60-day hold", "₦20,000 minimum". Those four sentences are advertising, and
    the shop is bound by them. `ReferralOverviewView` already argues this out for the
    signed-in dashboard — a hardcoded "10%" in JSX is a promise written somewhere that
    cannot change when the promise does. The public page needed the identical guarantee
    and had no way to get it, because every other endpoint in this app is
    `IsAuthenticated`.

    So this serves the SAME `settings.*` values the commission is actually calculated
    from. Change `REFERRAL_COMMISSION_PERCENT` and the advertisement moves with the
    payment, in one deploy, with no second place to remember.

    ── WHAT IT DOES NOT DISCLOSE ──────────────────────────────────────────────────

    Nothing about any person. No codes, no balances, no counts, no names. Every value
    below is already published at tokecosmetics.com/affiliates-2/ and printed on the
    terms, so this endpoint's entire content is a page of the contract. That is why it
    is `AllowAny` and unthrottled where `lookup/` is neither: there is nothing here to
    enumerate.

    ── A CURRENCY WITH NO `Currency` ROW IS SKIPPED, NOT GUESSED ──────────────────

    `format_money` needs the row (it reads `decimal_places` and `symbol`), and inventing
    a symbol for a missing one would publish a threshold in the wrong denomination. A
    currency the shop cannot format is a currency it should not be advertising a minimum
    in — and `services` already refuses to pay one out.
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        currencies = {c.code: c for c in Currency.objects.all()}

        thresholds = [
            {
                "currency": code,
                "amount": str(amount),
                "amount_display": format_money(amount, currencies[code]),
            }
            # SORTED, and every configured currency is listed. The storefront leads with
            # the visitor's own market but names the others too — a naira threshold shown
            # alone to a UK shopper reads as "£20,000" to anybody skimming.
            for code, amount in sorted(settings.REFERRAL_PAYOUT_THRESHOLDS.items())
            if code in currencies
        ]

        elite = [
            {
                "currency": code,
                "threshold": str(threshold),
                "threshold_display": format_money(threshold, currencies[code]),
                "club_name": club_name(threshold, currencies[code]),
                "window_days": settings.REFERRAL_ELITE_WINDOW_DAYS,
            }
            # NGN-only today, shaped as a list so it stays honest if that ever changes.
            for code, threshold in sorted(settings.REFERRAL_ELITE_THRESHOLDS.items())
            if code in currencies
        ]

        return Response({
            "commission_percent": str(settings.REFERRAL_COMMISSION_PERCENT),
            "cookie_days": settings.REFERRAL_COOKIE_DAYS,
            "hold_days": settings.REFERRAL_HOLD_DAYS,
            "terms_version": settings.REFERRAL_TERMS_VERSION,
            "payout_thresholds": thresholds,
            "elite_tiers": elite,
        })


class CommissionListView(APIView):
    """GET /api/v1/me/referrals/commissions/ — the activity feed, newest first.

    Adjustments ride along in the same response rather than getting their own endpoint:
    they belong in the same visual list (a clawback is an event in the referrer's
    earnings history, not a separate concept they should have to go looking for), and
    there are never many of them.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        commissions = (
            Commission.objects.filter(referrer=request.user)
            .select_related("order", "order__user", "currency", "payout")
        )
        paginator = _Page()
        page = paginator.paginate_queryset(commissions, request, view=self)
        body = paginator.get_paginated_response(
            CommissionSerializer(page, many=True).data
        ).data
        # Only on the first page: the adjustments list is short and unpaginated, and
        # repeating it under every page would make it look like there are more.
        if paginator.page.number == 1:
            adjustments = (
                ReferralAdjustment.objects.filter(referrer=request.user)
                .select_related("currency")[:20]
            )
            body["adjustments"] = AdjustmentSerializer(adjustments, many=True).data
        else:
            body["adjustments"] = []
        return Response(body)


class PayoutMethodView(APIView):
    """GET/PUT /api/v1/me/referrals/payout-methods/ — where the money goes.

    PUT rather than POST, and keyed on currency inside the body rather than in the path:
    a referrer has at most one account per currency, so this is a replace, and modelling
    it as a collection would invite a second account nobody can choose between.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_throttles(self):
        # ADDED to the defaults for writes, not substituted for them: assigning
        # `throttle_classes` here would strip the global user throttle from this view
        # and cap reads at the write rate. See PayoutMethodWriteThrottle for why the
        # write needs its own, much lower number (every change is an outbound email).
        throttles = super().get_throttles()
        if self.request.method == "PUT":
            throttles.append(PayoutMethodWriteThrottle())
        return throttles

    def get(self, request):
        methods = PayoutMethod.objects.filter(user=request.user).select_related("currency")
        return Response(PayoutMethodSerializer(methods, many=True).data)

    def put(self, request):
        s = PayoutMethodWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        currency = Currency.objects.filter(code=v["currency"].upper(), is_active=True).first()
        if currency is None:
            return Response({"error": "currency_unknown", "detail": "That currency is not available."},
                            status=status.HTTP_400_BAD_REQUEST)
        if services.threshold_for(currency.code) is None:
            # Refuse to store an account for a currency that can never be paid out — it
            # would sit there implying a payout is coming.
            return Response(
                {"error": "currency_not_payable",
                 "detail": f"{currency.code} balances cannot be paid out yet."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        method = services.save_payout_method(
            request.user, currency=currency, bank_name=v["bank_name"],
            account_name=v["account_name"], account_number=v["account_number"],
            bank_code=v.get("bank_code", ""), extra=v.get("extra") or {},
        )
        return Response(PayoutMethodSerializer(method).data)


class PayoutRequestListCreateView(APIView):
    """GET/POST /api/v1/me/referrals/payouts/ — history, and asking for the next one."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        requests_qs = (
            PayoutRequest.objects.filter(referrer=request.user).select_related("currency")
        )
        paginator = _Page()
        page = paginator.paginate_queryset(requests_qs, request, view=self)
        return paginator.get_paginated_response(
            PayoutRequestSerializer(page, many=True).data
        )

    def post(self, request):
        s = PayoutCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            payout = services.request_payout(
                request.user,
                s.validated_data["currency"].upper(),
                accept_terms=s.validated_data["accept_terms"],
            )
        except services.ReferralError as exc:
            return _referral_error(exc)
        return Response(PayoutRequestSerializer(payout).data, status=status.HTTP_201_CREATED)
