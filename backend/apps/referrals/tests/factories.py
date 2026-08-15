"""Test helpers for the referral suite.

Deliberately builds real Orders through the ORM rather than reaching for
`apps.orders.factories`: every assertion in this suite is about money derived from an
order's own columns (subtotal, discount, tax, and the country's `prices_include_tax`
flag), so the tests need to set those columns precisely and see the commission follow.
"""
from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.core.models import Country, Currency
from apps.orders.models import Order, OrderEvent
from apps.orders.numbers import next_order_number
from apps.referrals.services import ensure_profile


def customer(django_user_model, email: str, **kwargs):
    kwargs.setdefault("password", "pw12345!")
    return django_user_model.objects.create_user(email=email, **kwargs)


def referrer(django_user_model, email: str = "ref@x.com", **kwargs):
    """A customer with a referral profile already minted, and their code."""
    user = customer(django_user_model, email, **kwargs)
    return user, ensure_profile(user)


def ng() -> Country:
    return Country.objects.get(code="NG")


def gb() -> Country:
    return Country.objects.get(code="GB")


def make_order(
    *,
    user,
    country: Country | None = None,
    subtotal="10000.00",
    discount="0.00",
    tax="0.00",
    shipping="1500.00",
    status="processing",
    referral_code: str = "",
    placed_at=None,
) -> Order:
    country = country or ng()
    subtotal_d = Decimal(subtotal)
    discount_d = Decimal(discount)
    tax_d = Decimal(tax)
    shipping_d = Decimal(shipping)
    grand = (
        subtotal_d - discount_d + shipping_d
        if country.prices_include_tax
        else subtotal_d - discount_d + tax_d + shipping_d
    )
    return Order.objects.create(
        number=next_order_number(),
        user=user,
        email=user.email,
        country=country,
        currency=country.currency,
        status=status,
        subtotal=subtotal_d,
        discount_total=discount_d,
        tax_total=tax_d,
        shipping_total=shipping_d,
        grand_total=grand,
        referral_code=referral_code,
        placed_at=placed_at or timezone.now(),
    )


def mark_shipped(order: Order, *, when=None) -> OrderEvent:
    """Move an order to shipped AND write the timeline event the maturity sweep reads.

    Both halves matter: the sweep filters on `order.status` and then reads the
    `status:shipped` event for the date, so a test that only flips the status would
    silently exercise the "no shipping event" fallback branch instead of the real one.
    """
    order.status = "shipped"
    order.save(update_fields=["status"])
    event = OrderEvent.objects.create(order=order, type="status:shipped", message="test")
    if when is not None:
        # auto_now_add ignores an assigned value, so the timestamp is rewritten in place.
        OrderEvent.objects.filter(pk=event.pk).update(created_at=when)
        event.refresh_from_db()
    return event


def ngn() -> Currency:
    return Currency.objects.get(code="NGN")
