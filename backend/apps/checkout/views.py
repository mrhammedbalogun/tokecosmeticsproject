import hashlib
from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Address
from apps.accounts.throttling import (
    GuestCheckoutEmailThrottle,
    GuestCheckoutIPThrottle,
    ScopedRateThrottle,
)
from apps.accounts.turnstile import require_turnstile
from apps.carts.models import Cart
from apps.carts.serializers import serialize_cart
from apps.carts.services import add_item_reporting, get_or_create_cart
from apps.catalog.models import ProductVariant
from apps.checkout.serializers import (
    GuestCheckoutSerializer,
    GuestDeliveryOptionsSerializer,
    GuestGigCentresSerializer,
    GuestQuoteRequestSerializer,
    QuoteRequestSerializer,
    build_unsaved_address,
)
from apps.checkout.services.checkout import CheckoutError, place_order, retry_payment
from apps.orders.tokens import (
    TrackingTokenError,
    make_guest_order_token,
    read_guest_order_token,
)
from apps.checkout.services.idempotency import (
    IdempotencyConflict,
    IdempotencyKeyReused,
    begin,
    clear,
    finish,
    hash_payload,
)
from apps.checkout.services.quote import quote as quote_service
from apps.payments.gateways.base import GatewayError, GatewayNotConfigured
from apps.checkout.services.totals import compute_totals
from apps.core.country_context import resolve_country
from apps.delivery.carriers import priced_options_for_address
from apps.delivery.services import option_id_matches
from apps.payments.gateways.registry import active_gateways_for


class PaymentMethodsView(APIView):
    """GET /api/v1/checkout/payment-methods/?country=NG — active gateways for a country."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        country = resolve_country(request.query_params.get("country") or request.headers.get("X-Country"))
        return Response(active_gateways_for(country))


def _cart_lines(cart):
    """[(variant, qty)] for a cart, prefetching variants. Combo components included —
    they are ordinary lines carrying a group (apps/carts/models.py)."""
    return [(i.variant, i.quantity) for i in cart.items.select_related("variant").all()]


def _goods_subtotal(cart, country) -> Decimal:
    """What the goods actually cost after any bundle saving — the figure the delivery
    engine's free-shipping thresholds must be judged against.

    Quoting against the components' LIST total would give free delivery to an order that
    never reached the threshold, which is a real cost per order rather than a display bug.
    """
    from apps.combos.services import cart_combo_discount

    lines = _cart_lines(cart)
    totals = compute_totals(lines, country, combo_discount=cart_combo_discount(cart, country))
    return totals.subtotal - totals.combo_discount


class DeliveryOptionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        address = get_object_or_404(Address, pk=request.query_params.get("address_id"), user=request.user)
        cart = get_object_or_404(Cart, pk=request.query_params.get("cart_id"), user=request.user, status="active")
        lines = _cart_lines(cart)
        if not lines:
            raise ValidationError("Cart is empty.")
        return Response(
            priced_options_for_address(
                address, lines, _goods_subtotal(cart, request.country), request.country
            )
        )


class GigCentresView(APIView):
    """GET /api/v1/checkout/gig-centres/?address_id= — the pickup picker's list:
    active GIG centres sorted by distance from the address's pin (else its LGA
    centroid). Own-address only, same pattern as DeliveryOptionsView; empty list
    when the LGA has no active GIG coverage — the storefront then simply doesn't
    offer pickup."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from apps.delivery.gig.centres import nearest_centres
        from apps.delivery.gig.quotes import coverage_region, receiver_point

        address = get_object_or_404(
            Address, pk=request.query_params.get("address_id"), user=request.user
        )
        region = coverage_region(address, home_delivery=False)
        if region is None:
            return Response([])
        lat, lng = receiver_point(address, region)
        return Response(nearest_centres(lat, lng, limit=6))


class QuoteView(APIView):
    """Read-only totals + coupon preview (Plan-14). Never mutates."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        data = QuoteRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        cart = get_object_or_404(Cart, pk=v["cart_id"], user=request.user, status="active")
        delivery_amount = Decimal("0.00")
        if v.get("address_id") and v.get("delivery_option_id"):
            address = get_object_or_404(Address, pk=v["address_id"], user=request.user)
            lines = _cart_lines(cart)
            goods = _goods_subtotal(cart, request.country)
            # Same non-authoritative posture as below: an unknown/inactive centre id
            # just means the pickup row prices to the nearest centre (or is omitted).
            centre = None
            if v.get("gig_centre_id") is not None:
                from apps.delivery.models import GigCentre

                centre = GigCentre.objects.filter(
                    gig_centre_id=v["gig_centre_id"], is_active=True
                ).first()
            opts = priced_options_for_address(
                address, lines, goods, request.country, pickup_centre=centre
            )
            chosen = next(
                (o for o in opts
                 if option_id_matches(o["id"], v["delivery_option_id"]) and o["price"] is not None),
                None,
            )
            # Intentional silent fallback: an option id that doesn't match this address
            # (or is quote_required) just leaves delivery at 0.00 rather than erroring —
            # this is a non-authoritative preview, not a place_order. place_order does
            # its own server-side re-match and is the authoritative check.
            if chosen:
                delivery_amount = Decimal(chosen["price"])
        return Response(quote_service(
            cart, request.country, user=request.user,
            coupon_code=v.get("coupon_code", ""), delivery_amount=delivery_amount,
            referral_code=v.get("referral_code", ""),
        ))


# --- guest checkout (Plan-38) -------------------------------------------------
#
# SEPARATE views rather than AllowAny branches inside the authed ones, deliberately:
# the authed quoting paths run a live store and stay byte-identical. All three are
# POST (inline address = PII, GETs land in access logs) and all three demand a
# non-empty ACTIVE guest cart — the plausibility gate that stops naked anonymous
# requests driving the live GIG quote engine through cache-busting sweeps (the
# IP throttles here are store-wide shared buckets and cannot be tightened; see
# _IPKeyedThrottle's caveat).


def _guest_cart_or_404(cart_id):
    cart = get_object_or_404(Cart, pk=cart_id, user=None, status="active")
    return cart


class GuestDeliveryOptionsView(APIView):
    """POST /api/v1/checkout/guest/delivery-options/ — DeliveryOptionsView's guest
    twin: {cart_id, address:{...}}. Validating through GuestAddressSerializer here is
    also the guest address form's REAL validation pass — field errors surface on the
    form before the shopper ever reaches delivery."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        data = GuestDeliveryOptionsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        cart = _guest_cart_or_404(v["cart_id"])
        lines = _cart_lines(cart)
        if not lines:
            raise ValidationError("Cart is empty.")
        address = build_unsaved_address(v["address"])
        return Response(
            priced_options_for_address(
                address, lines, _goods_subtotal(cart, request.country), request.country
            )
        )


class GuestGigCentresView(APIView):
    """POST /api/v1/checkout/guest/gig-centres/ — GigCentresView's guest twin:
    {cart_id, address:{...}} → nearest active GIG centres for the inline address."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from apps.delivery.gig.centres import nearest_centres
        from apps.delivery.gig.quotes import coverage_region, receiver_point

        data = GuestGigCentresSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        cart = _guest_cart_or_404(v["cart_id"])
        if not cart.items.exists():
            raise ValidationError("Cart is empty.")
        address = build_unsaved_address(v["address"])
        region = coverage_region(address, home_delivery=False)
        if region is None:
            return Response([])
        lat, lng = receiver_point(address, region)
        return Response(nearest_centres(lat, lng, limit=6))


class GuestQuoteView(APIView):
    """POST /api/v1/checkout/guest/quote/ — QuoteView's guest twin. guest_email rides
    along so the coupon preview enforces the same per-email limits place_order will
    (quote.py threads it into validate_coupon). Same non-authoritative posture as
    QuoteView: a stale option id just leaves delivery at 0.00."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        data = GuestQuoteRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        cart = _guest_cart_or_404(v["cart_id"])
        delivery_amount = Decimal("0.00")
        if v.get("address") and v.get("delivery_option_id"):
            address = build_unsaved_address(v["address"])
            lines = _cart_lines(cart)
            goods = _goods_subtotal(cart, request.country)
            centre = None
            if v.get("gig_centre_id") is not None:
                from apps.delivery.models import GigCentre

                centre = GigCentre.objects.filter(
                    gig_centre_id=v["gig_centre_id"], is_active=True
                ).first()
            opts = priced_options_for_address(
                address, lines, goods, request.country, pickup_centre=centre
            )
            chosen = next(
                (o for o in opts
                 if option_id_matches(o["id"], v["delivery_option_id"]) and o["price"] is not None),
                None,
            )
            if chosen:
                delivery_amount = Decimal(chosen["price"])
        return Response(quote_service(
            cart, request.country, user=None, email=v.get("guest_email", ""),
            phone=v.get("guest_phone", ""),
            coupon_code=v.get("coupon_code", ""), delivery_amount=delivery_amount,
            referral_code=v.get("referral_code", ""),
        ))


class CheckoutView(APIView):
    """POST /api/v1/checkout/ — place an order. Authenticated customers, or guests
    (Plan-38): a guest request carries guest_email/guest_phone + an inline address
    and a Turnstile token.

    GUEST ORDERING IS DELIBERATE AND LOAD-BEARING: serializer validation (no
    idempotency state touched on a 400) → begin() → replay? answer the stored 201
    WITHOUT a Turnstile check (Turnstile tokens are single-use, and both documented
    same-key retry paths — the gateway-502 resume and the lost-201 replay — arrive
    carrying an already-consumed token; a replay does no work, so waving it through
    is safe) → require_turnstile → place_order. A Turnstile failure clears the
    inflight marker so the same key retries immediately with a fresh token.
    """

    permission_classes = [permissions.AllowAny]

    def get_throttles(self):
        # The defaults (anon/user) plus, for guests only, the two plan-38 caps: the
        # email key stops one address being mail-bombed with order confirmations,
        # the IP key caps direct-to-API volume (shared-egress caveat as everywhere).
        throttles = super().get_throttles()
        user = getattr(self.request, "user", None)
        if not (user and user.is_authenticated):
            throttles += [GuestCheckoutIPThrottle(), GuestCheckoutEmailThrottle()]
        return throttles

    def post(self, request):
        key = request.headers.get("Idempotency-Key")
        if not key:
            return Response({"error": "idempotency_key_required"}, status=status.HTTP_400_BAD_REQUEST)
        is_guest = not request.user.is_authenticated

        payload = {
            "cart_id": str(request.data.get("cart_id")),
            "address_id": request.data.get("address_id"),
            "billing_address_id": request.data.get("billing_address_id"),
            "delivery_option_id": request.data.get("delivery_option_id"),
            "coupon_code": request.data.get("coupon_code", ""),
            "payment_gateway": request.data.get("payment_gateway"),
            "gig_centre_id": request.data.get("gig_centre_id"),
            "pickup_store_id": request.data.get("pickup_store_id"),
        }
        guest = None
        if is_guest:
            gs = GuestCheckoutSerializer(data=request.data)
            gs.is_valid(raise_exception=True)
            guest = gs.validated_data
            # The guest's contact + RAW address ride the request hash: same key with a
            # different address/email is a genuinely different order (422), while a
            # byte-identical retry replays. The RAW dict (not validated_data) because
            # validated_data holds Region instances, and a legitimate retry resends
            # the same bytes anyway. turnstile_token stays OUT for the same reason
            # referral_code does below: it is volatile by design (single-use).
            payload["guest_email"] = guest["guest_email"]
            payload["guest_phone"] = guest["guest_phone"]
            payload["guest_address"] = request.data.get("address")
        # `referral_code` is DELIBERATELY ABSENT from the hashed payload above, having
        # briefly been in it. The hash exists to catch "same key, genuinely different
        # order" and answer 422; the attribution cookie is not part of what the customer
        # is buying, and it is VOLATILE — it expires on its own 30-day clock and changes
        # if they open another referrer's link. Hashing it means a legitimate retry of a
        # lost 201, sent with the same Idempotency-Key, can be refused as "key reused"
        # because a cookie moved between the two attempts. Left out, the first attempt's
        # attribution simply wins, which is both the safer failure and the fairer answer.
        referral_code = request.data.get("referral_code", "")
        # Ad attribution + consent (Plan-44). OUT of the hashed payload for exactly the
        # reason `referral_code` above is: it is volatile by design — a pixel cookie can
        # be written between a lost 201 and its retry — and hashing it would refuse a
        # legitimate retry as "key reused" because a tracking cookie moved. Like the
        # referral code, the first attempt's attribution simply wins.
        #
        # Unlike the referral code, it is read from the BODY rather than a cookie,
        # because the pixel cookies it carries are written by vendor JavaScript and the
        # storefront's BFF is the only thing that can read them. It decides nothing
        # about money; `marketing.capture` documents that trust boundary in full.
        marketing = request.data.get("marketing")
        request_hash = hash_payload(payload)

        # Idempotency identity. Authed: the user id (unforgeable). Guest: the cart
        # UUID — already the guest's whole identity in carts/services.py. The DURABLE
        # key is additionally rewritten to sha256("guest:{cart_id}:{key}") because the
        # Payment-row backstop cannot scope on `order__user` for user=None (that
        # renders `user IS NULL` = every guest order ever — the plan-38 dissent
        # blocker). 64 hex chars = exactly the column width.
        if is_guest:
            namespace = f"guest:{payload['cart_id']}"
            durable_key = hashlib.sha256(
                f"guest:{payload['cart_id']}:{key}".encode()
            ).hexdigest()
        else:
            namespace = request.user.id
            durable_key = key

        try:
            replay = begin(namespace, key, request_hash)
        except IdempotencyKeyReused:
            return Response({"error": "idempotency_key_reused"}, status=422)
        except IdempotencyConflict:
            return Response({"error": "idempotency_in_progress"}, status=409, headers={"Retry-After": "2"})
        if replay is not None:
            return Response(replay[1], status=replay[0])

        if is_guest:
            # AFTER the replay check (see class docstring), BEFORE any work. A failed
            # check must release the inflight marker or the same key is locked out for
            # the full INFLIGHT_TTL while the customer holds a fresh token.
            try:
                require_turnstile(request)
            except PermissionDenied:
                clear(namespace, key)
                raise

        try:
            result = place_order(
                user=request.user if not is_guest else None,
                country=request.country, key=durable_key,
                cart_id=payload["cart_id"], address_id=payload["address_id"],
                billing_address_id=payload["billing_address_id"],
                delivery_option_id=payload["delivery_option_id"],
                payment_gateway=payload["payment_gateway"],
                coupon_code=payload["coupon_code"],
                notes=request.data.get("notes", ""),
                expected_total=request.data.get("expected_total"),
                gig_centre_id=payload["gig_centre_id"],
                pickup_store_id=payload["pickup_store_id"],
                referral_code=referral_code,
                guest_email=guest["guest_email"] if guest else "",
                guest_phone=guest["guest_phone"] if guest else "",
                guest_address=build_unsaved_address(guest["address"]) if guest else None,
                marketing=marketing,
            )
        except CheckoutError as exc:
            body = {"error": exc.code, "detail": exc.detail, **exc.extra}
            return Response(body, status=exc.http)
        except GatewayNotConfigured:
            clear(namespace, key)
            return Response({"error": "gateway_not_configured",
                             "detail": "Payment method is not available right now."}, status=503)
        except GatewayError:
            # Gateway 5xx/timeout on initiate. Order stays pending; clearing the inflight
            # marker lets the customer retry with the SAME Idempotency-Key (resumes it).
            # NOTE: distinct from the 400 "gateway_unavailable" above, which means the
            # method isn't offered in this country. This one means the provider is down.
            # (A guest retry re-runs Turnstile with a fresh widget token — the
            # storefront resets the widget after every completed attempt.)
            clear(namespace, key)
            return Response({"error": "gateway_error",
                             "detail": "Payment provider is temporarily unavailable. Please retry."},
                            status=502)

        # The guest-order token rides the 201 (and its stored replay): the BFF moves it
        # into an httpOnly cookie and STRIPS it from the browser response — it is the
        # guest's only credential for the confirmation page and payment verify, and it
        # must never travel in a gateway return URL (Paystack's dashboard-callback
        # fallback drops our query string) or be readable by page JS.
        body = _payment_envelope(
            result,
            guest_token=make_guest_order_token(result.order.number) if is_guest else None,
        )
        finish(namespace, key, request_hash, status.HTTP_201_CREATED, body)
        return Response(body, status=status.HTTP_201_CREATED)


def _payment_envelope(result, guest_token: str | None = None) -> dict:
    """The payment block the storefront drives its launcher from. Shared by place_order
    and retry so the client has exactly one shape to understand."""
    init = getattr(result.order, "_initiate", None)
    body = {
        "order_number": result.order.number,
        "payment": {
            "gateway": result.payment.gateway,
            "action": init.action if init else "",
            "reference": result.payment.gateway_reference,
            "data": init.data if init else {},
        },
    }
    if guest_token:
        body["guest_order_token"] = guest_token
    return body


class OrderPayView(APIView):
    """POST /api/v1/orders/{number}/pay/ — re-open payment on an order that is still
    awaiting it, optionally switching gateway. The customer-facing escape hatch for a
    declined card: placement already converted the cart, so there is no checkout to redo.

    Not idempotency-tracked through begin()/finish() like CheckoutView: there is no cart
    to convert and no order to duplicate here, so the Payment row's unique idempotency_key
    is protection enough — a repeated key replays the same attempt (see retry_payment).

    Guests (Plan-38): a `guest_token` in the body — the signed guest-order token the
    checkout BFF holds in an httpOnly cookie — stands in for auth, scoped to the one
    order it names. The token names the order; the URL is checked AGAINST it. The
    durable key is namespaced sha256("guest-pay:{number}:{key}") for the same
    cross-guest-replay reason as CheckoutView. No Turnstile here: minting an attempt
    requires the token, which only ever exists after a Turnstile-gated placement.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request, number: str):
        key = request.headers.get("Idempotency-Key")
        if not key:
            return Response({"error": "idempotency_key_required"},
                            status=status.HTTP_400_BAD_REQUEST)
        is_guest = not request.user.is_authenticated
        if is_guest:
            raw = request.data.get("guest_token")
            token = raw if isinstance(raw, str) else ""
            if not token:
                return Response({"error": "authentication_required"},
                                status=status.HTTP_403_FORBIDDEN)
            try:
                signed_number = read_guest_order_token(token)
            except TrackingTokenError:
                # Same code as "no such order": an invalid token must not become an
                # oracle for which order numbers exist.
                return Response({"error": "order_not_found"}, status=404)
            if signed_number != number:
                return Response({"error": "order_not_found"}, status=404)
            key = hashlib.sha256(f"guest-pay:{number}:{key}".encode()).hexdigest()
        try:
            result = retry_payment(
                user=None if is_guest else request.user, order_number=number,
                payment_gateway=request.data.get("payment_gateway"), key=key,
                guest=is_guest,
            )
        except CheckoutError as exc:
            return Response({"error": exc.code, "detail": exc.detail, **exc.extra},
                            status=exc.http)
        except GatewayNotConfigured:
            return Response({"error": "gateway_not_configured",
                             "detail": "Payment method is not available right now."}, status=503)
        except GatewayError:
            # The attempt exists but never got a reference. Retrying with the SAME key
            # resumes it rather than opening yet another attempt.
            return Response({"error": "gateway_error",
                             "detail": "Payment provider is temporarily unavailable. Please retry."},
                            status=502)
        return Response(_payment_envelope(result), status=status.HTTP_200_OK)


class BuyNowView(APIView):
    """Buy Now = add to the shopper's ordinary cart; the client then navigates to
    checkout, which reads that same cart. Never clears existing lines — this cart is
    the shopper's bag, and clearing it here would silently destroy it. (Originally a
    separate `kind="express"` cart per Plan-08 D14, retired 2026-07-28: nothing ever
    read an express cart, so Buy Now produced an empty checkout. The Cart.kind field
    stays for the inert historical rows.)

    AllowAny since Plan-38: guests shop the same cart machinery (get_or_create_cart
    already resolves the X-Cart-Id guest cart), so guest Buy Now is just an
    anonymous add-to-cart — the same operation the AllowAny cart endpoints have
    always offered — followed by the client navigating to checkout."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "cart"

    def post(self, request):
        variant = get_object_or_404(ProductVariant, pk=request.data.get("variant_id"), is_active=True)
        qty = int(request.data.get("quantity", 1))
        cart = get_or_create_cart(request)
        _, added = add_item_reporting(cart, variant, qty, request.country)
        if not added:
            return Response(
                {"detail": "This item just sold out.", "code": "out_of_stock"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(serialize_cart(cart, request.country))
