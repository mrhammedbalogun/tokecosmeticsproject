"""Attribution and accrual: who gets credited, how much, and what must never happen."""
from __future__ import annotations

from decimal import Decimal

import pytest

from apps.referrals.models import Commission
from apps.referrals.services import (
    accrue_for_order,
    attribution_code_for_order,
    commission_base,
    ensure_profile,
)
from apps.referrals.tests.factories import customer, gb, make_order, ng, referrer


@pytest.mark.django_db
def test_code_is_stable_and_case_insensitive(django_user_model):
    user = customer(django_user_model, "a@b.com", first_name="Amina")
    first = ensure_profile(user)
    assert ensure_profile(user).pk == first.pk, "profile must not be re-minted per call"
    assert first.code.startswith("AMINA")
    assert attribution_code_for_order(first.code.lower(), customer(
        django_user_model, "buyer@x.com")) == first.code


@pytest.mark.django_db
def test_self_referral_is_refused_on_account_email_and_phone(django_user_model):
    ref_user, profile = referrer(django_user_model, "amina@x.com", phone="+2348012345678")

    # Same account.
    assert attribution_code_for_order(profile.code, ref_user) == ""

    # A second account sharing the email is impossible (unique), so the realistic dodge
    # is a second account on the same phone number.
    alt = customer(django_user_model, "amina.alt@x.com", phone="+2348012345678")
    assert attribution_code_for_order(profile.code, alt) == ""

    # An unrelated buyer is fine.
    stranger = customer(django_user_model, "stranger@x.com", phone="+2348099999999")
    assert attribution_code_for_order(profile.code, stranger) == profile.code


@pytest.mark.django_db
def test_blocked_referrer_and_unknown_code_earn_nothing(django_user_model):
    ref_user, profile = referrer(django_user_model)
    buyer = customer(django_user_model, "buyer@x.com")

    assert attribution_code_for_order("NOSUCHCODE", buyer) == ""

    profile.is_blocked = True
    profile.save(update_fields=["is_blocked"])
    assert attribution_code_for_order(profile.code, buyer) == ""


@pytest.mark.django_db
def test_commission_base_excludes_shipping_and_embedded_tax(django_user_model):
    """The published base is "net sales excluding shipping, taxes and returns"."""
    buyer = customer(django_user_model, "buyer@x.com")

    # Nigeria: prices INCLUDE tax, so the VAT sits inside subtotal and must come out.
    ng_country = ng()
    ng_country.prices_include_tax = True
    ng_country.save(update_fields=["prices_include_tax"])
    order = make_order(
        user=buyer, country=ng_country,
        subtotal="10000.00", discount="1000.00", tax="628.00", shipping="2500.00",
    )
    assert commission_base(order) == Decimal("8372.00")  # 10000 - 1000 - 628

    # GB: prices EXCLUDE tax, so it was never in subtotal and must NOT be subtracted.
    gb_country = gb()
    gb_country.prices_include_tax = False
    gb_country.save(update_fields=["prices_include_tax"])
    gb_order = make_order(
        user=buyer, country=gb_country,
        subtotal="100.00", discount="10.00", tax="18.00", shipping="5.00",
    )
    assert commission_base(gb_order) == Decimal("90.00")  # 100 - 10


@pytest.mark.django_db
def test_accrual_writes_a_pending_commission_at_ten_percent(django_user_model):
    ref_user, profile = referrer(django_user_model)
    buyer = customer(django_user_model, "buyer@x.com")
    order = make_order(user=buyer, subtotal="10000.00", referral_code=profile.code)

    commission = accrue_for_order(order)

    assert commission is not None
    assert commission.referrer_id == ref_user.pk
    assert commission.status == "pending"
    assert commission.rate_percent == Decimal("10.00")
    assert commission.amount == Decimal("1000.00")
    assert commission.matures_at is None, "clock starts at shipping, not payment"


@pytest.mark.django_db
def test_accrual_is_idempotent_for_redelivered_webhooks(django_user_model):
    _, profile = referrer(django_user_model)
    buyer = customer(django_user_model, "buyer@x.com")
    order = make_order(user=buyer, referral_code=profile.code)

    first = accrue_for_order(order)
    second = accrue_for_order(order)

    assert first.pk == second.pk
    assert Commission.objects.filter(order=order).count() == 1


@pytest.mark.django_db
def test_accrual_never_raises_even_when_everything_is_broken(django_user_model, monkeypatch):
    """The load-bearing guarantee: this runs inside the payment transaction.

    If it could raise, a bug here would roll back a payment that has already been
    charged at the gateway — the customer's money leaves and their order expires. The
    contract is that it returns None and logs instead, and the backfill command repairs.
    """
    _, profile = referrer(django_user_model)
    buyer = customer(django_user_model, "buyer@x.com")
    order = make_order(user=buyer, referral_code=profile.code)

    monkeypatch.setattr(
        "apps.referrals.services.commission_base",
        lambda _order: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert accrue_for_order(order) is None
    assert not Commission.objects.filter(order=order).exists()


@pytest.mark.django_db
def test_a_database_error_in_accrual_leaves_the_callers_transaction_usable(
    django_user_model, monkeypatch
):
    """A DB-level failure in accrual must leave the caller able to keep writing.

    This is the failure a bare try/except does NOT cover: a database error aborts the
    whole Postgres transaction and marks the connection `needs_rollback`, so the caller's
    next write — in production, `payment.save()` inside `_fulfil_locked` — would raise
    TransactionManagementError and the payment would break anyway.

    It pins the BEHAVIOUR, not the mechanism. Today the property holds twice over:
    `accrue_for_order` savepoints its write, and Django's `get_or_create` savepoints its
    INSERT independently — so removing either one on its own still leaves this green.
    That is fine and deliberate. The test exists to fail the day a write is added to the
    accrual path that has neither.

    NOT `transaction=True`, and that was a correction. The marker looked right — "this is
    about real transaction behaviour" — but a `transaction=True` test TRUNCATES every
    table when it finishes, taking the countries and currencies seeded by
    `core/migrations/0003` with them, so the next test in the run that needs Nigeria dies
    with `Country.DoesNotExist`. That is exactly what happened: green alone and in its own
    app, red in the full suite, right after `orders/tests/test_state.py`'s own
    `transaction=True` test.

    The default wrapper is the honest harness here anyway: it puts the test inside an
    atomic block, which is precisely the shape production has — `_fulfil_locked` runs
    inside the payment transaction — so the nested-atomic behaviour under test is the
    real one.
    """
    _, profile = referrer(django_user_model)
    buyer = customer(django_user_model, "buyer@x.com")
    order = make_order(user=buyer, referral_code=profile.code)
    # An amount too wide for the column (max_digits=12) makes Postgres itself reject the
    # INSERT with "numeric field overflow". A real database error, not a mocked
    # exception — a mock would raise in Python and never mark the connection broken,
    # which is precisely the state this test exists to exercise.
    monkeypatch.setattr(
        "apps.referrals.services._commission_amount",
        lambda _base, _rate: Decimal("99999999999999.99"),
    )

    from django.db import transaction as db_transaction

    with db_transaction.atomic():
        order.customer_note = "written before"
        order.save(update_fields=["customer_note"])
        accrue_for_order(order)  # hits the existing row; must not poison the transaction
        # THE ASSERTION THAT MATTERS: the caller can still write.
        order.admin_note = "written after"
        order.save(update_fields=["admin_note"])

    order.refresh_from_db()
    assert order.admin_note == "written after"


@pytest.mark.django_db
def test_order_without_a_referral_code_accrues_nothing(django_user_model):
    buyer = customer(django_user_model, "buyer@x.com")
    order = make_order(user=buyer, referral_code="")
    assert accrue_for_order(order) is None


@pytest.mark.django_db
def test_commission_base_subtracts_item_tax_only_when_delivery_is_taxed(django_user_model):
    """Plan-37 lets a market tax its delivery fee, which lands inside `tax_total`.
    The delivery slice was never part of the goods, so subtracting the WHOLE tax
    would shortchange the referrer by exactly that slice."""
    buyer = customer(django_user_model, "buyer@x.com")

    gb_country = gb()
    gb_country.prices_include_tax = True
    gb_country.tax_applies_to_delivery = True
    gb_country.save(update_fields=["prices_include_tax", "tax_applies_to_delivery"])
    order = make_order(
        user=buyer, country=gb_country,
        # VAT inside the £120 goods = £20; inside the £6 delivery = £1. tax_total
        # carries both, delivery_tax_total names the delivery slice.
        subtotal="120.00", discount="0.00", tax="21.00", delivery_tax="1.00",
        shipping="6.00",
    )
    assert commission_base(order) == Decimal("100.00")  # 120 - 20, NOT 120 - 21
