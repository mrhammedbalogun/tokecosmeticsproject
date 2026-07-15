from decimal import Decimal

from apps.pricing.services import ResolvedPrice


def test_resolved_price_holds_fields():
    rp = ResolvedPrice(
        amount=Decimal("1000.00"),
        compare_at=Decimal("1500.00"),
        currency="NGN",
        tax_rate=Decimal("7.50"),
        prices_include_tax=True,
    )
    assert rp.amount == Decimal("1000.00")
    assert rp.compare_at == Decimal("1500.00")
    assert rp.currency == "NGN"
    assert rp.tax_rate == Decimal("7.50")
    assert rp.prices_include_tax is True
