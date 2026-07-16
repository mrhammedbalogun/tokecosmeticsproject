"""format_money — the display side of the same decimal_places source of truth."""
from decimal import Decimal

import pytest

from apps.core.models import Currency
from apps.payments.money import format_money

pytestmark = pytest.mark.django_db


def test_formats_with_the_currency_symbol_and_thousands_separators():
    ngn = Currency.objects.get(code="NGN")
    assert format_money(Decimal("1234567.5"), ngn) == "₦1,234,567.50"


def test_respects_a_zero_decimal_currency():
    """The reason this exists instead of `|floatformat:2` in a template: hardcoding two
    decimals renders a zero-decimal amount 100x wrong in the customer's inbox."""
    jpy = Currency.objects.create(code="JPY", symbol="¥", decimal_places=0)
    assert format_money(Decimal("1500"), jpy) == "¥1,500"


def test_pads_to_the_currency_precision():
    ngn = Currency.objects.get(code="NGN")
    assert format_money(Decimal("5"), ngn) == "₦5.00"


def test_refuses_to_round_away_precision_it_cannot_show():
    """Same contract as to_minor: never silently quantize money."""
    ngn = Currency.objects.get(code="NGN")
    with pytest.raises(ValueError):
        format_money(Decimal("10.999"), ngn)
