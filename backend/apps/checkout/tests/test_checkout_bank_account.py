"""A manual gateway with no configured account is unavailable, and checkout has to know
that BEFORE phase 1 spends anything."""
from decimal import Decimal

import pytest

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import Cart, CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.checkout.services.checkout import CheckoutError, place_order
from apps.core.models import Country, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockMovement
from apps.orders.models import Order
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def _world(stock=10):
    # Seed migration already created NG + NGN, and payments 0002 already marks
    # bank_transfer active for NG — fetch, don't re-create (PK / unique collisions).
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    opt = DeliveryOptionFactory(currency=ngn, name="Lagos Flat", price="1500.00")
    opt.regions.add(lagos)
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=stock)
    return ng, ngn, variant, lagos, opt


def test_checkout_refuses_before_reserving_stock_when_no_account_exists(django_user_model):
    # Failing only at initiate() (phase 2) would leave an order holding stock for 24h and
    # a converted cart behind, and every retry would burn another 24h hold.
    ng, ngn, variant, lagos, opt = _world()
    user = django_user_model.objects.create_user(email="noacct@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=2,
                            unit_price_snapshot="1000.00")

    before = Order.objects.count()
    with pytest.raises(CheckoutError) as exc:
        place_order(user=user, country=ng, key="no-account-1", cart_id=cart.id,
                    address_id=addr.id, delivery_option_id=opt.id,
                    payment_gateway="bank_transfer")

    assert exc.value.code == "gateway_unavailable"
    assert Order.objects.count() == before
    assert StockMovement.objects.count() == 0  # nothing reserved
    assert variant.stock_items.get().reserved == 0
    assert Cart.objects.get(id=cart.id).status == "active"  # not converted
