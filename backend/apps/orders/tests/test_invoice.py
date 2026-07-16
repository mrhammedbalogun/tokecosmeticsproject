"""Invoices. The HTML carries all the logic and is testable anywhere; the PDF step is a
thin WeasyPrint wrapper whose native libs only exist on the Linux deploy target."""
from decimal import Decimal

import pytest

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.orders.invoice import render_invoice_html
from apps.orders.models import OrderItem

pytestmark = pytest.mark.django_db


def _order(number="TC-600001", **kw):
    ng = Country.objects.get(code="NG")
    order = OrderFactory(number=number, country=ng, currency=ng.currency, status="processing",
                         email="buyer@x.com", subtotal="900.00", shipping_total="100.00",
                         grand_total="1000.00", delivery_option_name="Lagos Island Same-Day",
                         shipping_address={"line1": "1 Awolowo Rd", "city": "Ikoyi",
                                           "region": "Lagos", "country": "NG"},
                         billing_address={"line1": "1 Awolowo Rd", "city": "Ikoyi",
                                          "region": "Lagos", "country": "NG"}, **kw)
    OrderItem.objects.create(order=order, product_name="Shea Butter", variant_name="200ml",
                             sku="SB-200", unit_price="450.00", line_total="900.00", quantity=2)
    return order


def test_invoice_shows_the_order_items_and_totals():
    html = render_invoice_html(_order())

    assert "TC-600001" in html
    assert "Shea Butter" in html
    assert "SB-200" in html
    assert "₦1,000.00" in html  # via format_money, not a hardcoded 2dp


def test_invoice_shows_the_billing_address():
    html = render_invoice_html(_order(number="TC-600002"))

    assert "Awolowo" in html


def test_invoice_reflects_refunds_at_render_time():
    """The reason invoices generate on demand instead of being stored to S3: a stored PDF
    keeps asserting the original total long after a refund changed the commercial reality.
    Rendering now means the document cannot go stale."""
    from apps.core.models import Currency
    from apps.payments.models import Payment, Refund

    order = _order(number="TC-600003")
    payment = Payment.objects.create(order=order, gateway="paystack", amount=Decimal("1000.00"),
                                     currency=Currency.objects.get(code="NGN"),
                                     status="partially_refunded", gateway_reference="ref-600003")
    Refund.objects.create(payment=payment, amount=Decimal("250.00"), status="succeeded")

    html = render_invoice_html(order)

    assert "250.00" in html  # the refund appears...
    assert "₦750.00" in html  # ...and so does what the customer actually paid


def test_invoice_dates_its_refund_note_to_render_time_not_order_time():
    """The refund note says "as at <date>". Dating it from placed_at would claim the
    refund position was accurate as at a date BEFORE any refund could have settled."""
    from django.utils import timezone

    from apps.core.models import Currency
    from apps.payments.models import Payment, Refund

    old = timezone.now() - timezone.timedelta(days=90)
    order = _order(number="TC-600005", placed_at=old)
    payment = Payment.objects.create(order=order, gateway="paystack", amount=Decimal("1000.00"),
                                     currency=Currency.objects.get(code="NGN"),
                                     status="partially_refunded", gateway_reference="ref-600005")
    Refund.objects.create(payment=payment, amount=Decimal("250.00"), status="succeeded")

    html = render_invoice_html(order)

    assert timezone.now().strftime("%d %b %Y") in html
    assert f"settled as at {old.strftime('%d %b %Y')}" not in html


def test_invoice_ignores_refunds_that_have_not_settled():
    from apps.core.models import Currency
    from apps.payments.models import Payment, Refund

    order = _order(number="TC-600004")
    payment = Payment.objects.create(order=order, gateway="paystack", amount=Decimal("1000.00"),
                                     currency=Currency.objects.get(code="NGN"),
                                     status="succeeded", gateway_reference="ref-600004")
    Refund.objects.create(payment=payment, amount=Decimal("250.00"), status="pending")

    html = render_invoice_html(order)

    assert "Refunded" not in html  # a refund that hasn't settled isn't money back yet
