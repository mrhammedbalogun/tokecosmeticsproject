import pytest
from decimal import Decimal
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.delivery.factories import DeliveryOptionFactory
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.models import Order
from apps.payments.models import BankAccount, CountryPaymentGateway
from apps.pricing.models import Price
from apps.shipping.models import ShippingQuote

pytestmark = pytest.mark.django_db


def _row_world(quote_required=True, stock=10):
    zz = Country.objects.get(code="ZZ")        # currency USD, is_rest_of_world
    usd = zz.currency
    wh = WarehouseFactory(name="Intl Hub", location_country="NG", priority=1)
    wh.serves_countries.add(zz)
    # bank_transfer must be active for ZZ and have an account to pay into.
    CountryPaymentGateway.objects.update_or_create(
        country=zz, gateway="bank_transfer", defaults={"is_active": True}
    )
    BankAccount.objects.get_or_create(
        country=zz, defaults=dict(currency=usd, bank_name="Intl Bank",
                                  account_name="Toke", account_number="INTL-1",
                                  extra={"SWIFT BIC": "ABCDEF12"}),
    )
    opt = DeliveryOptionFactory(
        currency=usd, name="Adex International delivery", price="0.00",
        quote_required=quote_required,
        disclaimer="Shipping quoted after you order — typically $35–70.",
    )
    opt.countries.add(zz)
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=usd, amount=Decimal("100.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=stock)
    return zz, usd, variant, opt


def _place(django_user_model, zz, usd, variant, opt, email="de@x.com"):
    user = django_user_model.objects.create_user(email=email, password="pw")
    addr = Address.objects.create(user=user, line1="1 Berlin", country_code="DE")
    cart = CartFactory(user=user, country=zz, currency=usd)
    CartItem.objects.create(cart=cart, variant=variant, quantity=1,
                            unit_price_snapshot="100.00")
    client = APIClient()
    client.force_authenticate(user)
    r = client.post("/api/v1/checkout/",
                    {"cart_id": str(cart.id), "address_id": addr.id,
                     "delivery_option_id": opt.id, "payment_gateway": "bank_transfer"},
                    format="json", HTTP_X_COUNTRY="ZZ", HTTP_IDEMPOTENCY_KEY=email)
    return r


def test_row_order_is_born_with_an_awaiting_quote_row(django_user_model):
    """Created at placement, not at quote time."""
    zz, usd, variant, opt = _row_world()
    r = _place(django_user_model, zz, usd, variant, opt, email="de1@x.com")
    assert r.status_code == 201, r.data

    order = Order.objects.get(number=r.data["order_number"])
    quote = ShippingQuote.objects.get(order=order)
    assert quote.status == "awaiting_quote"
    assert quote.amount is None
    assert quote.currency_id == order.currency_id


def test_row_order_total_excludes_freight(django_user_model):
    """Customer pays goods only. shipping_total is 0 and grand == subtotal (ZZ has 0 tax)."""
    zz, usd, variant, opt = _row_world()
    r = _place(django_user_model, zz, usd, variant, opt, email="de2@x.com")
    assert r.status_code == 201, r.data

    order = Order.objects.get(number=r.data["order_number"])
    assert order.shipping_total == Decimal("0.00")
    assert order.grand_total == order.subtotal


def test_normal_option_gets_no_shipping_quote(django_user_model):
    """A non-quote_required option must NOT create a ShippingQuote."""
    zz, usd, variant, opt = _row_world(quote_required=False)
    r = _place(django_user_model, zz, usd, variant, opt, email="de3@x.com")
    assert r.status_code == 201, r.data

    order = Order.objects.get(number=r.data["order_number"])
    assert not ShippingQuote.objects.filter(order=order).exists()
