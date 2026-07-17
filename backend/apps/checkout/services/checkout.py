"""Checkout orchestration. Two-phase: everything money/stock happens in ONE DB txn
(phase 1); the external gateway call happens AFTER commit (phase 2) so no HTTP is ever
held under a DB lock. Raises CheckoutError(code, detail, extra) which the view maps to
409/400. All money comes from compute_totals; delivery price is re-derived server-side."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from functools import partial

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Address
from apps.carts.models import Cart
from apps.catalog.services import sellable_in
from apps.checkout.services.coupons import validate_coupon
from apps.checkout.services.totals import compute_totals
from apps.delivery.services import options_for_address
from apps.inventory.services import InsufficientStock, reserve
from apps.orders.emails import enqueue_order_received
from apps.orders.models import Order, OrderItem
from apps.orders.numbers import next_order_number
from apps.orders.state import record_event
from apps.payments.gateways.registry import active_gateways_for, get_gateway
from apps.payments.models import Payment
from apps.pricing.services import resolve_price


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
    }


def place_order(*, user, country, key: str, cart_id, address_id, delivery_option_id,
                payment_gateway: str, billing_address_id=None, coupon_code: str = "",
                notes: str = "", expected_total=None) -> CheckoutResult:
    # Durable backstop: a payment already exists for this key.
    existing = Payment.objects.filter(idempotency_key=key, order__user=user).select_related("order").first()
    if existing:
        # If a prior attempt created the order but the gateway initiate failed (5xx), the
        # payment has no gateway_reference yet — resume by re-attempting initiate (may
        # raise GatewayError again, which the view maps to 502). Never a duplicate order.
        if not existing.gateway_reference:
            _initiate_payment(existing, existing.order)
        return CheckoutResult(order=existing.order, payment=existing)

    with transaction.atomic():
        cart = Cart.objects.select_for_update().filter(pk=cart_id, user=user).first()
        if cart is None or cart.status != "active":
            raise CheckoutError("cart_not_active", "Cart is not active.")
        lines = [(i.variant, i.quantity) for i in cart.items.select_related("variant__product").all()]
        if not lines:
            raise CheckoutError("cart_empty", "Cart is empty.")

        address = Address.objects.filter(pk=address_id, user=user).first()
        if address is None:
            raise CheckoutError("address_invalid", "Address not found.", http=400)
        billing = address
        if billing_address_id:
            billing = Address.objects.filter(pk=billing_address_id, user=user).first() or address

        # Re-validate every line against live catalog + pricing.
        for variant, qty in lines:
            if not sellable_in(variant.product, country):
                raise CheckoutError("line_unavailable", f"{variant.sku} is not available.",
                                    extra={"sku": variant.sku})

        # Server-side delivery re-match — never trust the client's option list.
        subtotal_preview = compute_totals(lines, country).subtotal
        options = options_for_address(address, lines, subtotal_preview, country)
        chosen = next((o for o in options if o["id"] == delivery_option_id), None)
        if chosen is None:
            raise CheckoutError("delivery_option_invalid", "Delivery option not valid for this address.")

        # Gateway must be active for the country.
        if payment_gateway not in {g["gateway"] for g in active_gateways_for(country)}:
            raise CheckoutError("gateway_unavailable", "Payment method not available.", http=400)

        # A manual gateway needs a configured account BEFORE we reserve stock. Failing at
        # initiate() (phase 2, post-commit) would leave an order holding stock for the full
        # 24h TTL and a converted cart, and every retry would burn another hold.
        gateway = get_gateway(payment_gateway)
        if gateway.confirmation == "manual":
            from apps.payments.models import BankAccount

            if not BankAccount.objects.filter(country=country, is_active=True).exists():
                raise CheckoutError(
                    "gateway_unavailable", "Payment method not available.", http=400
                )

        # Coupon (optional).
        coupon = None
        if coupon_code:
            product_ids = {v.product_id for v, _ in lines}
            result = validate_coupon(coupon_code, subtotal_preview, country, user=user,
                                     email=user.email, item_product_ids=product_ids)
            if not result.ok:
                raise CheckoutError(f"coupon_{result.error_code}", "Coupon not valid.", http=400)
            coupon = result.coupon

        totals = compute_totals(lines, country, delivery_amount=Decimal(chosen["price"]), coupon=coupon)

        if expected_total is not None and Decimal(str(expected_total)) != totals.grand_total:
            raise CheckoutError("cart_changed", "Totals changed.",
                                extra={"totals": _totals_dict(totals)})

        number = next_order_number()
        try:
            for variant, qty in lines:
                reserve(variant, qty, country, reference=number)
        except InsufficientStock as exc:
            raise CheckoutError("insufficient_stock", str(exc)) from exc

        order = Order.objects.create(
            number=number, user=user, email=user.email, phone=user.phone,
            country=country, currency=country.currency, status="pending_payment",
            subtotal=totals.subtotal, discount_total=totals.discount,
            shipping_total=totals.delivery, tax_total=totals.tax, grand_total=totals.grand_total,
            coupon=coupon, delivery_option_name=chosen["name"],
            shipping_address=_address_snapshot(address), billing_address=_address_snapshot(billing),
            customer_note=notes, reservation_reference=number,
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
        for variant, qty in lines:
            rp = resolve_price(variant, country)
            OrderItem.objects.create(
                order=order, variant=variant, product_name=variant.product.name,
                variant_name=", ".join(f"{k}: {v}" for k, v in (variant.option_values or {}).items()),
                sku=variant.sku, unit_price=rp.amount, line_total=(rp.amount * qty), quantity=qty,
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


def _initiate_payment(payment, order) -> None:
    """Call the gateway to start collecting money and persist what it returns. Raises
    GatewayError/GatewayNotConfigured on failure — the order stays pending_payment and
    the attempt is safely retryable (see the durable backstop above)."""
    init = get_gateway(payment.gateway).initiate(payment, order)
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


def _totals_dict(t) -> dict:
    return {
        "subtotal": str(t.subtotal), "discount": str(t.discount), "delivery": str(t.delivery),
        "tax": str(t.tax), "grand_total": str(t.grand_total), "currency": t.currency,
    }
