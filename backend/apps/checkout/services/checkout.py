"""Checkout orchestration. Two-phase: everything money/stock happens in ONE DB txn
(phase 1); the external gateway call happens AFTER commit (phase 2) so no HTTP is ever
held under a DB lock. Raises CheckoutError(code, detail, extra) which the view maps to
409/400. All money comes from compute_totals; delivery price is re-derived server-side."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from functools import partial

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Address
from apps.carts.models import Cart
from apps.catalog.images import variant_image_path
from apps.catalog.services import sellable_in
from apps.checkout.services.coupons import validate_coupon
from apps.checkout.services.totals import compute_totals
from apps.delivery.carriers import priced_options_for_address
from apps.delivery.services import option_id_matches
from apps.inventory.services import InsufficientStock, reserve
from apps.orders.emails import enqueue_order_received, enqueue_staff_awaiting_transfer
from apps.orders.models import Order, OrderItem
from apps.orders.numbers import next_order_number
from apps.orders.state import record_event
from apps.payments.gateways.registry import active_gateways_for, get_gateway
from apps.payments.models import Payment
from apps.pricing.services import resolve_price
from apps.referrals.services import attribution_code_for_order


class CheckoutError(Exception):
    def __init__(self, code: str, detail: str = "", extra: dict | None = None, http: int = 409):
        self.code = code
        self.detail = detail or code
        self.extra = extra or {}
        self.http = http
        super().__init__(self.detail)


@dataclass
class CheckoutResult:
    order: Order
    payment: Payment


def _address_snapshot(addr: Address) -> dict:
    return {
        "first_name": addr.first_name, "last_name": addr.last_name, "phone": addr.phone,
        "line1": addr.line1, "line2": addr.line2, "country_code": addr.country_code,
        "state": addr.state_region.name if addr.state_region else addr.state_text,
        "area": addr.area_region.name if addr.area_region else addr.city_text,
        "postcode": addr.postcode,
        # The pin rides into the snapshot so the waybill ships door coordinates even
        # if the customer edits the address after placing (Plan-32b ruling 2). Floats:
        # the snapshot is JSON and 6dp survives float round-tripping.
        "latitude": float(addr.latitude) if addr.latitude is not None else None,
        "longitude": float(addr.longitude) if addr.longitude is not None else None,
    }


def _store_snapshot(store) -> dict:
    """Order.pickup_store's shape — the full address and the counter phone, because
    this snapshot is what the ready-for-pickup email and the order page print."""
    return {
        "id": store.id, "name": store.name, "address": store.address,
        "phone": store.phone,
        "state": store.state_region.name if store.state_region else store.state,
    }


def place_order(*, user, country, key: str, cart_id, address_id=None, delivery_option_id=None,
                payment_gateway: str = "", billing_address_id=None, coupon_code: str = "",
                notes: str = "", expected_total=None, gig_centre_id=None,
                pickup_store_id=None,
                referral_code: str = "", guest_email: str = "", guest_phone: str = "",
                guest_address=None) -> CheckoutResult:
    """Place an order for an authenticated customer OR a guest (Plan-38).

    Guest path: ``user=None`` with ``guest_email``/``guest_phone`` (validated +
    E.164-normalised by GuestCheckoutSerializer) and ``guest_address`` — an UNSAVED
    Address instance; the quoting engine and ``_address_snapshot`` only read fields
    and forward FKs off it, so no address row is ever written. Billing = shipping
    for guests, deliberately (v1 ruling, plan-38).

    ``key`` on the guest path is NOT the client's raw Idempotency-Key: the view hands
    in sha256("guest:{cart_id}:{client_key}"). The durable backstop below matches on
    the stored key alone for guests — with user=None a filter on ``order__user`` would
    render ``user IS NULL``, i.e. "any guest order ever placed", letting one guest
    replay another's key and read back their payment envelope (bank details included).
    The cart-UUID-namespaced hash is what scopes the lookup instead; the cart UUID is
    already the guest's whole identity (carts/services.py), so knowing it IS being
    that guest.
    """
    if user is not None:
        # Durable backstop: a payment already exists for this key, for THIS user.
        existing = (
            Payment.objects.filter(idempotency_key=key, order__user=user)
            .select_related("order").first()
        )
    else:
        existing = Payment.objects.filter(idempotency_key=key).select_related("order").first()
    if existing:
        # If a prior attempt created the order but the gateway initiate failed (5xx), the
        # payment has no SDK material yet (raw_response is set only after a successful
        # initiate; the reference alone is persisted BEFORE the call) — resume by
        # re-attempting initiate (may raise GatewayError again, which the view maps to
        # 502). Never a duplicate order.
        if not existing.raw_response:
            _initiate_payment(existing, existing.order)
        return CheckoutResult(order=existing.order, payment=existing)

    with transaction.atomic():
        # For a guest (user=None) this filter renders `user IS NULL` — exactly the
        # guest-cart ownership rule (the UUID is the identity, carts/services.py).
        cart = Cart.objects.select_for_update().filter(pk=cart_id, user=user).first()
        if cart is None or cart.status != "active":
            raise CheckoutError("cart_not_active", "Cart is not active.")
        lines = [(i.variant, i.quantity) for i in cart.items.select_related("variant__product").all()]
        if not lines:
            raise CheckoutError("cart_empty", "Cart is empty.")

        if user is not None:
            address = Address.objects.filter(pk=address_id, user=user).first()
            if address is None:
                raise CheckoutError("address_invalid", "Address not found.", http=400)
            billing = address
            if billing_address_id:
                billing = Address.objects.filter(pk=billing_address_id, user=user).first() or address
        else:
            # Guest: the validated, UNSAVED Address instance. Billing = shipping.
            address = guest_address
            if address is None:
                raise CheckoutError("address_invalid", "Address not found.", http=400)
            billing = address

        # Re-validate every line against live catalog + pricing.
        for variant, qty in lines:
            if not sellable_in(variant.product, country):
                raise CheckoutError("line_unavailable", f"{variant.sku} is not available.",
                                    extra={"sku": variant.sku})

        # Server-side delivery re-match — never trust the client's option list.
        # The chosen pickup centre (32b slice 4) resolves FIRST so the pickup row is
        # priced to the centre the parcel will actually travel to, not the nearest.
        centre = None
        if gig_centre_id is not None:
            from apps.delivery.models import GigCentre

            centre = GigCentre.objects.filter(gig_centre_id=gig_centre_id, is_active=True).first()
            if centre is None:
                raise CheckoutError("centre_invalid", "That pickup centre is not available.")
        subtotal_preview = compute_totals(lines, country).subtotal
        options = priced_options_for_address(
            address, lines, subtotal_preview, country, pickup_centre=centre
        )
        # str-compared via option_id_matches: ids are mixed int/"pz:{pk}" since Plan-39.
        chosen = next((o for o in options if option_id_matches(o["id"], delivery_option_id)), None)
        if chosen is None:
            raise CheckoutError("delivery_option_invalid", "Delivery option not valid for this address.")
        is_pickup = chosen.get("carrier_service") == "pickup" and chosen.get("carrier_code") == "gig"
        if is_pickup and centre is None:
            # The picker is not optional for pickup: "which centre" is the address.
            raise CheckoutError("centre_required", "Choose a pickup centre for this delivery option.")

        # Store pickup (Plan-40): same shape as the centre rules above — the store IS
        # the destination, so it is not optional, and it is re-validated server-side
        # against the ADDRESS'S state rather than trusted from the client. A store
        # whose flag or state changed since the options render answers store_invalid.
        store = None
        if chosen.get("kind") == "store":
            from apps.delivery.models import SenderLocation

            if pickup_store_id is None:
                raise CheckoutError("store_required", "Choose a store for this pickup option.")
            store = SenderLocation.objects.filter(
                pk=pickup_store_id, is_active=True, customer_pickup=True,
                state_region_id=address.state_region_id,
            ).select_related("state_region").first()
            if store is None:
                raise CheckoutError("store_invalid", "That pickup store is not available.")

        # Gateway must be active for the country, and a manual gateway needs a configured
        # account BEFORE we reserve stock: failing at initiate() (phase 2, post-commit)
        # would leave an order holding stock for the full 24h TTL and a converted cart,
        # and every retry would burn another hold.
        gateway = _gateway_offered(payment_gateway, country)

        # Coupon (optional).
        coupon = None
        if coupon_code:
            product_ids = {v.product_id for v, _ in lines}
            # Guests validate against their submitted email — coupons.py already
            # falls back to email__iexact for per-user limits when user is None.
            coupon_email = user.email if user is not None else guest_email
            result = validate_coupon(coupon_code, subtotal_preview, country, user=user,
                                     email=coupon_email, item_product_ids=product_ids)
            if not result.ok:
                raise CheckoutError(f"coupon_{result.error_code}", "Coupon not valid.", http=400)
            coupon = result.coupon

        # A quote_required option has no price yet — the customer pays goods only and
        # the freight is quoted afterwards (see the ShippingQuote created below). Coerce
        # to 0 for the goods total rather than letting Decimal(None) raise.
        delivery_amount = (
            Decimal("0.00") if chosen["quote_required"] else Decimal(chosen["price"])
        )
        totals = compute_totals(lines, country, delivery_amount=delivery_amount, coupon=coupon)

        if expected_total is not None and Decimal(str(expected_total)) != totals.grand_total:
            raise CheckoutError("cart_changed", "Totals changed.",
                                extra={"totals": _totals_dict(totals)})

        # Referral attribution. THIS IS THE LAST MOMENT IT CAN HAPPEN: the code comes
        # from a 30-day cookie the storefront's BFF read off the checkout request, and
        # payment confirmation runs off a gateway webhook with no browser behind it. So
        # the code is resolved and validated here (unknown / blocked / self-referral all
        # collapse to "") and stamped on the order; the money row is written later, from
        # the payment path, off this stamp. Never raises — see referrals.services.
        attributed_code = attribution_code_for_order(referral_code, user)

        number = next_order_number()
        try:
            for variant, qty in lines:
                reserve(variant, qty, country, reference=number)
        except InsufficientStock as exc:
            raise CheckoutError("insufficient_stock", str(exc)) from exc

        order = Order.objects.create(
            number=number, user=user,
            email=user.email if user is not None else guest_email,
            phone=user.phone if user is not None else guest_phone,
            country=country, currency=country.currency, status="pending_payment",
            subtotal=totals.subtotal, discount_total=totals.discount,
            shipping_total=totals.delivery, tax_total=totals.tax,
            delivery_tax_total=totals.delivery_tax, grand_total=totals.grand_total,
            coupon=coupon, delivery_option_name=chosen["name"],
            pickup_store=_store_snapshot(store) if store else {},
            shipping_address=_address_snapshot(address), billing_address=_address_snapshot(billing),
            customer_note=notes, reservation_reference=number,
            referral_code=attributed_code,
            # Per-gateway: a card resolves in seconds, a bank transfer waits on staff
            # working hours. The gateway is already known and validated here, and its
            # Payment row is created in this same transaction, so nothing needs
            # re-stamping at initiate time.
            reservation_expires_at=timezone.now()
            + timedelta(minutes=gateway.reservation_ttl_minutes),
        )
        # A creation, not a transition — there is no prior status to move from, so this
        # opens the timeline directly rather than going through the state machine.
        record_event(order, "placed", actor=user, message=f"{chosen['name']} to {country.code}")
        if chosen["quote_required"]:
            # Born at placement, in the same transaction as the order: the awaiting_quote
            # queue is how staff learn this order needs a freight quote at all. Created
            # later (at quote time) it would be an absence, and absences are invisible.
            from apps.shipping.models import ShippingQuote

            ShippingQuote.objects.create(order=order, currency=country.currency)
        if chosen["kind"] == "carrier" and chosen.get("carrier_code") == "gig":
            # Same reasoning as ShippingQuote above: the GigShipment row is how
            # fulfilment learns this order ships via GIG, so it is born with the order.
            from apps.delivery.gig.shipments import create_quoted_shipment

            create_quoted_shipment(
                order, chosen, charged=totals.delivery,
                centre=centre if is_pickup else None,
            )
        for variant, qty in lines:
            rp = resolve_price(variant, country)
            OrderItem.objects.create(
                order=order, variant=variant, product_name=variant.product.name,
                variant_name=", ".join(f"{k}: {v}" for k, v in (variant.option_values or {}).items()),
                sku=variant.sku, unit_price=rp.amount, line_total=(rp.amount * qty), quantity=qty,
                # A SNAPSHOT, like `product_name` and `sku` beside it. The field has
                # existed since orders/0001 and nothing ever wrote it, so every order
                # placed before today carries "" — the email templates fall back to
                # resolving from the `variant` FK for those.
                #
                # Snapshotted rather than always resolved live because this is the picture
                # of the thing they bought. Re-shoot the product next season and a
                # re-opened confirmation email should still show what was in the box, for
                # the same reason `product_name` is frozen here rather than followed.
                image_path=variant_image_path(variant),
            )
        payment = Payment.objects.create(
            order=order, gateway=payment_gateway, amount=totals.grand_total,
            currency=country.currency, status="initiated", idempotency_key=key,
        )
        cart.status = "converted"
        cart.save(update_fields=["status", "updated_at"])

    # Phase 2 — external call AFTER commit, no lock held.
    _initiate_payment(payment, order)
    return CheckoutResult(order=order, payment=payment)


def _gateway_offered(payment_gateway: str, country):
    """The shared "may this customer pay with this, here?" gate. Returns the gateway.

    Both entry points must ask BOTH questions — is it switched on for the market, and (for
    a manual gateway) is there an account to pay into. A retry that skipped the second
    would hand the customer a payment page with no account number on it.
    """
    if payment_gateway not in {g["gateway"] for g in active_gateways_for(country)}:
        raise CheckoutError("gateway_unavailable", "Payment method not available.", http=400)
    gateway = get_gateway(payment_gateway)
    if gateway.confirmation == "manual":
        from apps.payments.models import BankAccount

        if not BankAccount.objects.filter(country=country, is_active=True).exists():
            raise CheckoutError("gateway_unavailable", "Payment method not available.", http=400)
    return gateway


def retry_payment(*, user, order_number: str, payment_gateway: str, key: str,
                  guest: bool = False) -> CheckoutResult:
    """Open a NEW payment attempt for an order that is still awaiting payment, possibly on
    a different gateway.

    Why this exists: place_order converts the cart in the same transaction that creates the
    order, BEFORE initiate. So a customer whose card is declined has no bag to return to,
    and the durable backstop in place_order only re-initiates when the payment never got a
    gateway_reference — after a successful initiate that a customer then abandoned, it
    replays a response with no SDK material in it. Without this, that order is unpayable.

    Deliberately narrow: the order's lines, addresses, totals and stock reservation are NOT
    recomputed. Re-quoting here would let a price move between attempts change what the
    customer already agreed to. Only the money leg is re-opened.

    The previous attempt is left exactly as it is. Its transaction may still settle at the
    gateway, and if it does, confirm_payment's NOOP_ALREADY_PROCESSED branch flags the
    order for a refund — which is the correct outcome and already covered. Cancelling the
    row here would only make our records disagree with the gateway's.
    """
    # Durable backstop, same shape as place_order: a payment already exists for this key.
    # Guest path (Plan-38): `guest=True` means the caller has ALREADY proven access to
    # this order via the signed guest-order token, and `key` arrives namespaced as
    # sha256("guest-pay:{order_number}:{client_key}") — so the backstop matches on the
    # key scoped to the order's own number. Filtering `order__user=None` here instead
    # would be the cross-guest replay hole plan-38's dissent review flagged.
    if guest:
        existing = (
            Payment.objects.filter(idempotency_key=key, order__number=order_number)
            .select_related("order").first()
        )
    else:
        existing = (
            Payment.objects.filter(idempotency_key=key, order__user=user)
            .select_related("order").first()
        )
    if existing:
        # raw_response, not gateway_reference: the reference is persisted before the
        # gateway call, so only the SDK material proves initiate finished (same marker
        # as place_order's backstop above).
        if not existing.raw_response:
            _initiate_payment(existing, existing.order)
        return CheckoutResult(order=existing.order, payment=existing)

    # Guest lookup is by number alone — the token is the credential, and it must keep
    # working even after the order is claimed by a verifying account (the person
    # holding the checkout-session cookie and the person who owns that account are
    # the same customer mid-payment).
    order_filter = (
        {"number": order_number} if guest else {"number": order_number, "user": user}
    )
    order = (
        Order.objects.filter(**order_filter)
        .select_related("country", "currency").first()
    )
    if order is None:
        # Same code for "no such order" and "not yours" — never confirm an order number
        # exists to someone who doesn't own it.
        raise CheckoutError("order_not_found", "Order not found.", http=404)
    if order.status != "pending_payment":
        raise CheckoutError(
            "order_not_payable", "This order is no longer awaiting payment.", http=409
        )

    gateway = _gateway_offered(payment_gateway, order.country)

    # Mirror the amount of the last goods attempt rather than order.grand_total: a
    # quote_required (RoW) order is deliberately paid goods-only, with freight quoted
    # afterwards, so grand_total would ask for money nobody has quoted yet.
    previous = order.payments.filter(purpose="goods").order_by("-created_at").first()
    amount = previous.amount if previous else order.grand_total

    with transaction.atomic():
        payment = Payment.objects.create(
            order=order, gateway=payment_gateway, amount=amount, currency=order.currency,
            status="initiated", idempotency_key=key, purpose="goods",
        )
        # Switching to a slower method (card -> bank transfer) must not leave the order
        # expiring in minutes while the customer is actively paying. Forward only: a retry
        # can never shorten a hold that is already longer.
        new_expiry = timezone.now() + timedelta(minutes=gateway.reservation_ttl_minutes)
        if order.reservation_expires_at and new_expiry > order.reservation_expires_at:
            order.reservation_expires_at = new_expiry
            order.save(update_fields=["reservation_expires_at", "updated_at"])
        record_event(order, "payment_retried", actor=user,
                     message=f"new attempt via {payment_gateway}")

    # Phase 2 — external call AFTER commit, no lock held (same rule as place_order).
    _initiate_payment(payment, order)
    return CheckoutResult(order=order, payment=payment)


def _initiate_payment(payment, order) -> None:
    """Call the gateway to start collecting money and persist what it returns. Raises
    GatewayError/GatewayNotConfigured on failure — the order stays pending_payment and
    the attempt is safely retryable (see the durable backstop above)."""
    # The service mints the gateway reference, not the adapters. At every gateway we use,
    # the reference IS the transaction identity, so each attempt needs its own: the first
    # goods attempt keeps the bare order reference (the exact bytes the Paystack
    # certification ran on), every later attempt is "-P<pk>"-suffixed. Reusing a
    # reference across attempts is what produced the retry 500 (IntegrityError on
    # uniq_payment_gateway_reference, Flutterwave TC-100056, 2026-08-12).
    #
    # Persisted BEFORE the network call (intent-then-act): if initiate crashes after the
    # gateway created a transaction, the reference in our row is the handle to find it —
    # previously that link existed gateway-side with no trace in the DB. "Initiate
    # succeeded" is therefore marked by raw_response (the SDK material), no longer by
    # gateway_reference — the backstops check accordingly.
    if not payment.gateway_reference:
        is_first_attempt = not (
            order.payments.filter(purpose="goods").exclude(pk=payment.pk).exists()
        )
        payment.gateway_reference = (
            order.reservation_reference if is_first_attempt
            else f"{order.reservation_reference}-P{payment.pk}"
        )
        payment.save(update_fields=["gateway_reference", "updated_at"])

    # Server-built return URL: the trusted storefront origin + THIS attempt's reference
    # (PaymentStatusView resolves ?ref= by gateway_reference, so the customer returns to
    # the verify of the attempt they actually paid). Never accept a return URL from the
    # client (open-redirect / tampering). Only the redirect gateway (Flutterwave) acts on
    # it; the inline gateways ignore it.
    return_url = (
        f"{settings.STOREFRONT_BASE_URL.rstrip('/')}"
        f"/checkout/return?ref={payment.gateway_reference}"
    )
    init = get_gateway(payment.gateway).initiate(payment, order, return_url=return_url)
    payment.gateway_reference = init.reference
    payment.raw_response = init.data
    payment.save(update_fields=["gateway_reference", "raw_response", "updated_at"])
    order._initiate = init  # stash for the view's response

    # `bank_details` means exactly "the customer leaves checkout owing money and holding
    # instructions" — and those instructions live ONLY in this response, so closing the
    # tab loses the account number AND the reference they must quote. Keyed off the
    # action rather than a gateway flag: it's already the right question, and it stays
    # right for a future Paystack dedicated account (also not instant, also needs this).
    # A card customer is mid-redirect and owes nothing on paper, so they get nothing here.
    if init.action == "bank_details":
        transaction.on_commit(partial(enqueue_order_received, order.pk, init.data))
        # And the other half of the same fact: money is now EXPECTED. Only the staff mail
        # can start the 24h clock for whoever watches the bank account — until this
        # existed, the first anyone here heard of a transfer order was when somebody
        # confirmed its payment, which required already knowing it was there.
        # Deliberately inside the same branch: an instant-gateway order that is abandoned
        # mid-redirect is not news, and alerting on those would make this list noise.
        #
        # A RETRY RE-ALERTS, ON PURPOSE. `retry_payment` routes back through here, so a
        # customer who switches card -> bank transfer produces a second alert for one
        # order. Suppressing on "this order already has a goods payment" was considered
        # and rejected: that condition is TRUE for the card -> transfer switch, which is
        # precisely the case where nobody has been told to watch for money yet. The
        # duplicate is also not identical — a retry pushes `reservation_expires_at`
        # forward, so the second mail carries a later deadline than the first, and that
        # is the number whoever is matching bank statements acts on.
        #
        # REGISTERED AFTER the customer's `enqueue_order_received` above, and that
        # ordering is load-bearing: on_commit callbacks are not independent (see
        # orders/state.py). `enqueue_staff_awaiting_transfer` also guards itself.
        transaction.on_commit(partial(enqueue_staff_awaiting_transfer, order.pk))


def _totals_dict(t) -> dict:
    return {
        "subtotal": str(t.subtotal), "discount": str(t.discount), "delivery": str(t.delivery),
        "tax": str(t.tax), "grand_total": str(t.grand_total), "currency": t.currency,
    }
