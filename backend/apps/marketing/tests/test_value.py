"""What `value` means on a Purchase, and the coupling it is built on."""
from __future__ import annotations

from decimal import Decimal

import pytest

from apps.marketing.tests.factories import customer, enable_tracking, gb, make_order, ng
from apps.marketing.value import currency_code, purchase_value


@pytest.mark.django_db
def test_goods_is_net_of_every_discount_and_excludes_shipping(django_user_model):
    user = customer(django_user_model, "a@x.com")
    order = make_order(user=user, subtotal="50000.00", discount="1000.00",
                       referral_discount="2500.00", shipping="1500.00")
    enable_tracking(purchase_value_basis="goods")

    assert purchase_value(order) == Decimal("46500.00")


@pytest.mark.django_db
def test_grand_total_is_everything_the_customer_was_charged(django_user_model):
    user = customer(django_user_model, "a@x.com")
    order = make_order(user=user, subtotal="50000.00", shipping="1500.00")
    enable_tracking(purchase_value_basis="grand_total")

    assert purchase_value(order) == Decimal(order.grand_total)


@pytest.mark.django_db
def test_the_goods_basis_agrees_with_what_the_shop_pays_referrers_on(django_user_model):
    """**The coupling, pinned.**

    `value.purchase_value` borrows `referrals.services.commission_base` rather than
    re-deriving the tax branch, and `value.py` says why: the branch (VAT inside the
    subtotal for Nigeria, added on top for GB/US/CA) is exactly the part that would be
    got wrong twice.

    This test is the seatbelt on that borrowing. If the referral programme's definition
    of net sales ever needs to differ from what is reported to the ad platforms, this
    fails — which is the moment to fork `purchase_value`, NOT to edit `commission_base`.
    """
    from apps.referrals.services import commission_base

    user = customer(django_user_model, "a@x.com")
    enable_tracking(purchase_value_basis="goods")

    # Nigeria: prices include tax, so the VAT sits INSIDE the subtotal.
    inclusive = make_order(user=user, country=ng(), subtotal="50000.00", tax="3488.37",
                           delivery_tax="0.00", shipping="1500.00")
    assert purchase_value(inclusive) == commission_base(inclusive)

    # GB: tax added on top, so it was never in the subtotal and must not come out.
    exclusive = make_order(user=user, country=gb(), subtotal="400.00", tax="80.00",
                           shipping="10.00")
    assert purchase_value(exclusive) == commission_base(exclusive)


@pytest.mark.django_db
def test_currency_is_the_orders_own_and_never_a_converted_one(django_user_model):
    """Each market bills in its own currency and the platforms convert. Converting here
    would report a number no invoice anywhere agrees with."""
    user = customer(django_user_model, "a@x.com")
    assert currency_code(make_order(user=user, country=ng())) == "NGN"
    assert currency_code(make_order(user=user, country=gb())) == "GBP"
