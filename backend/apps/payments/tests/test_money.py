"""money.to_minor / from_minor centralize the arithmetic of converting a Decimal
amount to/from a gateway's minor unit, reading Currency.decimal_places (NGN=2,
zero-decimal currencies=0). Adapters own the *convention* (which unit a gateway wants);
this module owns the *math* and refuses to silently round money it can't represent."""
from decimal import Decimal

import pytest

from apps.core.models import Country, Currency
from apps.payments.money import from_minor, to_minor

pytestmark = pytest.mark.django_db


def _ngn():
    return Country.objects.get(code="NG").currency  # decimal_places=2


def _zero_decimal():
    # A zero-decimal currency (like JPY/KRW/XOF) — minor unit == major unit.
    return Currency.objects.create(code="JPY", symbol="¥", decimal_places=0)


def test_to_minor_two_decimal_currency():
    assert to_minor(Decimal("1000.00"), _ngn()) == 100000
    assert to_minor(Decimal("10.99"), _ngn()) == 1099
    assert to_minor(Decimal("0.01"), _ngn()) == 1


def test_from_minor_two_decimal_currency():
    assert from_minor(100000, _ngn()) == Decimal("1000.00")
    assert from_minor(1099, _ngn()) == Decimal("10.99")


def test_zero_decimal_currency_is_identity():
    jpy = _zero_decimal()
    assert to_minor(Decimal("5000"), jpy) == 5000
    assert from_minor(5000, jpy) == Decimal("5000")


def test_to_minor_raises_on_excess_precision():
    # NGN allows 2 places; 3 places cannot be represented in kobo without rounding.
    with pytest.raises(ValueError):
        to_minor(Decimal("10.999"), _ngn())


def test_roundtrip():
    ngn = _ngn()
    amount = Decimal("12345.67")
    assert from_minor(to_minor(amount, ngn), ngn) == amount
