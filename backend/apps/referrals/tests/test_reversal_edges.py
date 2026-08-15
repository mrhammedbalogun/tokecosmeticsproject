"""The money bugs Fable 5 found in the finished implementation (2026-08-14).

Each test here corresponds to a defect that survived the first round of tests, so each
one names the failure it prevents rather than the behaviour it observes. They are in
their own module because they are all about the SEAMS — refund vs sweep vs payout
release — and reading them together is what makes the interaction legible.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models import Country
from apps.payments.models import Payment, Refund
from apps.referrals.models import Commission, ReferralAdjustment
from apps.referrals.services import (
    accrue_for_order,
    balances,
    mark_payout_paid,
    recompute_for_order,
    reject_payout,
    request_payout,
    reverse_for_refund,
    save_payout_method,
)
from apps.referrals.tasks import mature_commissions
from apps.referrals.tests.factories import customer, make_order, ngn, referrer


def _setup(django_user_model, **order_kwargs):
    ref_user, profile = referrer(django_user_model)
    buyer = customer(django_user_model, "buyer@x.com")
    order = make_order(user=buyer, referral_code=profile.code, **order_kwargs)
    return ref_user, profile, order, accrue_for_order(order)


def _refund(order, amount: str, *, status="succeeded"):
    """A real Refund row against a real Payment, so `refunded_total_for` can find it.

    The idempotency key is per-order, not blank: `Payment.idempotency_key` is UNIQUE, so
    a second blank one collides — which is a real constraint doing its job, not something
    to work around by reusing one payment across orders.
    """
    payment = order.payments.first() or Payment.objects.create(
        order=order, gateway="bank_transfer", amount=order.grand_total,
        currency=order.currency, status="succeeded",
        idempotency_key=f"test-{order.number}",
    )
    return Refund.objects.create(
        payment=payment, amount=Decimal(amount), status=status,
    )


def _fund_and_claim(django_user_model, ref_user, profile, subtotal="300000.00"):
    """Earn enough to clear the threshold and open a payout on it."""
    buyer = customer(django_user_model, "big@x.com")
    order = make_order(user=buyer, subtotal=subtotal, referral_code=profile.code)
    commission = accrue_for_order(order)
    Commission.objects.filter(pk=commission.pk).update(status="available")
    save_payout_method(ref_user, currency=ngn(), bank_name="GTBank",
                       account_name="A OKORO", account_number="0123456789")
    return order, commission, request_payout(ref_user, "NGN", accept_terms=True)


# --- 1. gross refunds against a net base -------------------------------------------


@pytest.mark.django_db
def test_a_partial_refund_on_a_tax_inclusive_order_does_not_under_pay(django_user_model):
    """The refund is GROSS, the base is NET. Subtracting one from the other directly
    docks the referrer the tax fraction on every partial refund."""
    ng = Country.objects.get(code="NG")
    ng.prices_include_tax = True
    ng.tax_rate_percent = Decimal("7.50")
    ng.save(update_fields=["prices_include_tax", "tax_rate_percent"])

    # ₦10,750 gross goods, of which ₦750 is VAT → base ₦10,000, commission ₦1,000.
    _ref, _p, order, commission = _setup(
        django_user_model, subtotal="10750.00", tax="750.00", shipping="0.00",
    )
    assert commission.amount == Decimal("1000.00")

    # Exactly half the goods come back, gross.
    reverse_for_refund(order, Decimal("5375.00"))

    commission.refresh_from_db()
    # Half the sale survived, so half the commission does. The naive subtraction gives
    # ₦462.50 here — a 7.5% shortfall, systematically, in the shop's favour.
    assert commission.amount == Decimal("500.00")


@pytest.mark.django_db
def test_a_refund_larger_than_the_goods_does_not_drive_the_base_negative(django_user_model):
    _ref, _p, order, commission = _setup(
        django_user_model, subtotal="10000.00", shipping="3500.00",
    )
    reverse_for_refund(order, Decimal("13500.00"))  # goods + shipping

    commission.refresh_from_db()
    assert commission.status == "reversed"


# --- 2. the sweep, claimed commissions, and the release path ------------------------


@pytest.mark.django_db
def test_an_order_cancelled_while_its_payout_is_open_still_gets_clawed_back(
    django_user_model,
):
    """THE HOLE: a claimed commission is `paid`, and a sweep that only touched
    pending/available let the payout go out at full value with no clawback at all."""
    ref_user, profile = referrer(django_user_model)
    order, commission, payout = _fund_and_claim(django_user_model, ref_user, profile)

    order.status = "cancelled"
    order.save(update_fields=["status"])
    mature_commissions()

    commission.refresh_from_db()
    assert commission.status == "paid", "a claimed row is never rewritten"
    clawback = ReferralAdjustment.objects.get(referrer=ref_user, order=order)
    assert clawback.amount == Decimal("-30000.00")
    assert payout.amount == Decimal("30000.00"), "the payout itself still adds up"


@pytest.mark.django_db
def test_the_sweep_and_the_webhook_do_not_each_mint_a_clawback(django_user_model):
    """Two paths reversing the same order must converge, not stack."""
    ref_user, profile = referrer(django_user_model)
    order, _c, _payout = _fund_and_claim(django_user_model, ref_user, profile)
    _refund(order, "303500.00")
    order.status = "refunded"
    order.save(update_fields=["status"])

    reverse_for_refund(order, Decimal("303500.00"))  # the webhook
    mature_commissions()                              # then the sweep
    mature_commissions()                              # and again tomorrow

    rows = ReferralAdjustment.objects.filter(referrer=ref_user, order=order)
    assert rows.count() == 1
    assert rows.first().amount == Decimal("-30000.00")


@pytest.mark.django_db
def test_rejecting_a_payout_does_not_dock_a_refund_twice(django_user_model):
    """The four-step bug: claimed → refunded (clawback minted) → payout rejected →
    commission released at FULL value with the clawback still standing → the next
    recompute reduces the row as well. Same refund, taken twice."""
    ref_user, profile = referrer(django_user_model)
    staff = customer(django_user_model, "staff@x.com", is_staff=True)
    order, commission, payout = _fund_and_claim(django_user_model, ref_user, profile)

    # A third of the goods come back while the payout sits in review.
    _refund(order, "100000.00")
    reverse_for_refund(order, Decimal("100000.00"))
    assert ReferralAdjustment.objects.filter(referrer=ref_user, order=order).count() == 1

    reject_payout(payout.pk, staff_user=staff, customer_message="Confirm your account name.")

    commission.refresh_from_db()
    assert commission.status == "available", "released back to the referrer"
    # The reduction now lives on the ROW, and the stale clawback is gone.
    assert commission.amount == Decimal("20000.00")
    assert not ReferralAdjustment.objects.filter(
        referrer=ref_user, order=order, kind="clawback"
    ).exists()

    wallet = next(w for w in balances(ref_user) if w.currency.code == "NGN")
    assert wallet.available == Decimal("20000.00"), "docked once, not twice"


# --- 3 & 4. the sweep survives a bad row, and repairs a missed reversal -------------


@pytest.mark.django_db
def test_one_broken_pass_does_not_stop_the_others(django_user_model, monkeypatch):
    """All three passes used to share one transaction, so a single poison row rolled
    back the lot — and would again tomorrow, and every day after, silently."""
    _ref, _p, order, commission = _setup(django_user_model)
    from apps.referrals.tests.factories import mark_shipped

    mark_shipped(order, when=timezone.now() - timezone.timedelta(days=61))

    monkeypatch.setattr(
        "apps.referrals.tasks._recompute_affected",
        lambda: (_ for _ in ()).throw(RuntimeError("poison row")),
    )
    result = mature_commissions()

    assert result["recomputed"] == 0
    assert result["stamped"] == 1 and result["released"] == 1, "the other passes still ran"
    commission.refresh_from_db()
    assert commission.status == "available"


@pytest.mark.django_db
def test_the_sweep_repairs_a_reversal_that_was_swallowed(django_user_model):
    """`reverse_for_refund` catches everything so a refund is never blocked. Without a
    repair pass, a reversal that threw is a silent permanent over-payment."""
    _ref, _p, order, commission = _setup(
        django_user_model, subtotal="10000.00", shipping="0.00",
    )
    _refund(order, "4000.00")
    # The live hook never ran (or threw and was swallowed) — the commission is untouched.
    assert commission.amount == Decimal("1000.00")

    mature_commissions()

    commission.refresh_from_db()
    assert commission.amount == Decimal("600.00")


@pytest.mark.django_db
def test_the_sweep_reports_commissions_it_failed_to_release(django_user_model, monkeypatch):
    """A silently-broken sweep and a sweep with nothing to do look identical without
    this number."""
    _ref, _p, order, _c = _setup(django_user_model)
    from apps.referrals.tests.factories import mark_shipped

    mark_shipped(order, when=timezone.now() - timezone.timedelta(days=90))
    monkeypatch.setattr("apps.referrals.tasks._release_matured", lambda: 0)

    assert mature_commissions()["stalled"] == 1


# --- 5. a payout row cannot be deleted out from under its commissions ---------------


@pytest.mark.django_db
def test_a_payout_cannot_be_deleted_while_it_holds_commissions(django_user_model):
    """Under SET_NULL this stranded the money: commissions stuck at `paid` pointing at
    nothing, invisible to every balance and unrecoverable without hand-written SQL."""
    from django.db.models import ProtectedError

    ref_user, profile = referrer(django_user_model)
    _order, _commission, payout = _fund_and_claim(django_user_model, ref_user, profile)

    with pytest.raises(ProtectedError):
        payout.delete()


# --- 6. lifetime is not path-dependent ---------------------------------------------


@pytest.mark.django_db
def test_lifetime_is_the_same_whichever_side_of_the_payout_a_refund_lands(
    django_user_model,
):
    """Two economically identical returns must not produce two different "earned all
    time" figures just because one arrived a day later."""
    # (a) refunded BEFORE payout — the commission reverses out of lifetime.
    ref_a, profile_a = referrer(django_user_model, "a@x.com")
    buyer_a = customer(django_user_model, "ba@x.com")
    order_a = make_order(user=buyer_a, subtotal="300000.00", referral_code=profile_a.code)
    commission_a = accrue_for_order(order_a)
    Commission.objects.filter(pk=commission_a.pk).update(status="available")
    _refund(order_a, "303500.00")
    recompute_for_order(order_a)
    lifetime_a = next(w for w in balances(ref_a) if w.currency.code == "NGN").lifetime

    # (b) refunded AFTER payout — the commission stays `paid`, a clawback nets it out.
    ref_b, profile_b = referrer(django_user_model, "b@x.com")
    staff = customer(django_user_model, "staff2@x.com", is_staff=True)
    order_b, _cb, payout_b = _fund_and_claim(django_user_model, ref_b, profile_b)
    mark_payout_paid(payout_b.pk, staff_user=staff, reference="GTB/1")
    _refund(order_b, "303500.00")
    recompute_for_order(order_b)
    lifetime_b = next(w for w in balances(ref_b) if w.currency.code == "NGN").lifetime

    assert lifetime_a == lifetime_b == Decimal("0.00")


# --- 9a. the email-domain flag is a signal, not the base rate ----------------------


@pytest.mark.django_db
def test_a_shared_free_email_domain_is_not_a_fraud_flag(django_user_model):
    from apps.referrals.services import fraud_flags

    ref_user, profile = referrer(django_user_model, "amina@gmail.com")
    _order, _c, payout = _fund_and_claim(django_user_model, ref_user, profile)
    order = payout.commissions.first().order
    order.email = "someone.else@gmail.com"
    order.save(update_fields=["email"])

    assert not any("email domain" in f for f in fraud_flags(payout))


# --- account deletion must not leave bank details behind ---------------------------


@pytest.mark.django_db
def test_deleting_an_account_removes_the_bank_details_but_keeps_the_payment_record(
    django_user_model,
):
    """Adding a PII table means the deletion sweep has to know about it. It scrubbed
    addresses and order snapshots and knew nothing about payout details until this."""
    from apps.accounts.tasks import _anonymize_one
    from apps.referrals.models import PayoutMethod, PayoutRequest

    ref_user, profile = referrer(django_user_model, "leaving@x.com", first_name="Amina")
    _order, _c, payout = _fund_and_claim(django_user_model, ref_user, profile)
    staff = customer(django_user_model, "staff3@x.com", is_staff=True)
    mark_payout_paid(payout.pk, staff_user=staff, reference="GTB/2026/0099")

    ref_user.is_active = False
    ref_user.deletion_requested_at = timezone.now() - timezone.timedelta(days=90)
    ref_user.save(update_fields=["is_active", "deletion_requested_at"])

    assert _anonymize_one(ref_user.pk) is True

    # The standing instruction is gone.
    assert not PayoutMethod.objects.filter(user=ref_user).exists()

    # The record of money the shop actually sent survives, minus the account number.
    payout = PayoutRequest.objects.get(pk=payout.pk)
    assert payout.amount == Decimal("30000.00")
    assert payout.reference == "GTB/2026/0099"
    assert payout.method_snapshot["bank_name"] == "GTBank"
    assert payout.method_snapshot["account_number"] == "••••6789"
    assert "0123456789" not in str(payout.method_snapshot)
