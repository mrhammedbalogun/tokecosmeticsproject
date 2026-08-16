"""Balances, thresholds and the payout lifecycle."""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.core.models import Currency
from apps.referrals.models import Commission, PayoutRequest, ReferralAdjustment
from apps.referrals.services import (
    ReferralError,
    accrue_for_order,
    balances,
    mark_payout_paid,
    reject_payout,
    request_payout,
    save_payout_method,
    tier_progress,
)
from apps.referrals.tests.factories import customer, make_order, ngn, referrer


def _earn(django_user_model, ref_user, profile, amount_subtotal: str, *, status="available",
          buyer_email="buyer@x.com", placed_at=None):
    buyer = customer(django_user_model, buyer_email)
    order = make_order(
        user=buyer, subtotal=amount_subtotal, referral_code=profile.code,
        placed_at=placed_at,
    )
    commission = accrue_for_order(order)
    if status != "pending":
        Commission.objects.filter(pk=commission.pk).update(status=status)
        commission.refresh_from_db()
    return commission


def _with_method(user):
    return save_payout_method(
        user, currency=ngn(), bank_name="GTBank", account_name="AMINA OKORO",
        account_number="0123456789",
    )


@pytest.mark.django_db
def test_balance_separates_pending_from_available(django_user_model):
    ref_user, profile = referrer(django_user_model)
    _earn(django_user_model, ref_user, profile, "100000.00", status="available")
    _earn(django_user_model, ref_user, profile, "50000.00", status="pending",
          buyer_email="b2@x.com")

    wallet = next(w for w in balances(ref_user) if w.currency.code == "NGN")
    assert wallet.available == Decimal("10000.00")
    assert wallet.pending == Decimal("5000.00")
    assert wallet.lifetime == Decimal("10000.00"), "pending is not earned yet"


@pytest.mark.django_db
def test_payout_is_refused_below_the_published_threshold(django_user_model):
    ref_user, profile = referrer(django_user_model)
    _with_method(ref_user)
    _earn(django_user_model, ref_user, profile, "100000.00")  # ₦10,000 — under ₦20,000

    wallet = next(w for w in balances(ref_user) if w.currency.code == "NGN")
    assert wallet.can_request is False

    with pytest.raises(ReferralError) as exc:
        request_payout(ref_user, "NGN", accept_terms=True)
    assert exc.value.code == "below_threshold"


@pytest.mark.django_db
def test_the_first_payout_request_must_accept_the_terms(django_user_model):
    ref_user, profile = referrer(django_user_model)
    _with_method(ref_user)
    _earn(django_user_model, ref_user, profile, "300000.00")  # ₦30,000

    with pytest.raises(ReferralError) as exc:
        request_payout(ref_user, "NGN", accept_terms=False)
    assert exc.value.code == "terms_required"

    payout = request_payout(ref_user, "NGN", accept_terms=True)
    assert payout.amount == Decimal("30000.00")

    profile.refresh_from_db()
    assert profile.terms_accepted_at is not None
    assert profile.terms_version


@pytest.mark.django_db
def test_a_payout_request_needs_a_bank_account_first(django_user_model):
    ref_user, profile = referrer(django_user_model)
    _earn(django_user_model, ref_user, profile, "300000.00")

    with pytest.raises(ReferralError) as exc:
        request_payout(ref_user, "NGN", accept_terms=True)
    assert exc.value.code == "payout_method_required"


@pytest.mark.django_db
def test_requesting_claims_the_commissions_so_a_second_tab_cannot_double_request(
    django_user_model,
):
    ref_user, profile = referrer(django_user_model)
    _with_method(ref_user)
    commission = _earn(django_user_model, ref_user, profile, "300000.00")

    payout = request_payout(ref_user, "NGN", accept_terms=True)

    commission.refresh_from_db()
    assert commission.status == "paid"
    assert commission.payout_id == payout.pk

    wallet = next(w for w in balances(ref_user) if w.currency.code == "NGN")
    assert wallet.available == Decimal("0.00")
    assert wallet.can_request is False

    with pytest.raises(ReferralError) as exc:
        request_payout(ref_user, "NGN", accept_terms=True)
    assert exc.value.code == "payout_already_open"


@pytest.mark.django_db
def test_a_clawback_is_netted_into_the_payout_and_settled_once(django_user_model):
    ref_user, profile = referrer(django_user_model)
    _with_method(ref_user)
    _earn(django_user_model, ref_user, profile, "300000.00")  # ₦30,000
    ReferralAdjustment.objects.create(
        referrer=ref_user, currency=ngn(), amount=Decimal("-5000.00"),
        kind="clawback", reason="returned after payout",
    )

    payout = request_payout(ref_user, "NGN", accept_terms=True)
    assert payout.amount == Decimal("25000.00")

    adjustment = ReferralAdjustment.objects.get(referrer=ref_user)
    assert adjustment.settled_by_id == payout.pk

    # And it must not be netted a second time against future earnings.
    _earn(django_user_model, ref_user, profile, "300000.00", buyer_email="b2@x.com")
    wallet = next(w for w in balances(ref_user) if w.currency.code == "NGN")
    assert wallet.available == Decimal("30000.00")


@pytest.mark.django_db
def test_rejecting_releases_the_commissions_and_the_clawback(django_user_model):
    """A rejection that stranded the money would be a data-loss button."""
    ref_user, profile = referrer(django_user_model)
    staff = customer(django_user_model, "staff@x.com", is_staff=True)
    _with_method(ref_user)
    _earn(django_user_model, ref_user, profile, "300000.00")
    ReferralAdjustment.objects.create(
        referrer=ref_user, currency=ngn(), amount=Decimal("-5000.00"),
        kind="clawback", reason="returned after payout",
    )
    payout = request_payout(ref_user, "NGN", accept_terms=True)

    reject_payout(payout.pk, staff_user=staff, customer_message="Please confirm your account name.")

    wallet = next(w for w in balances(ref_user) if w.currency.code == "NGN")
    assert wallet.available == Decimal("25000.00"), "commission back, clawback back too"
    assert wallet.can_request is True


@pytest.mark.django_db
def test_marking_paid_requires_a_bank_reference_and_mails_the_referrer(
    django_user_model, django_capture_on_commit_callbacks
):
    ref_user, profile = referrer(django_user_model)
    staff = customer(django_user_model, "staff@x.com", is_staff=True)
    _with_method(ref_user)
    _earn(django_user_model, ref_user, profile, "300000.00")
    payout = request_payout(ref_user, "NGN", accept_terms=True)

    with pytest.raises(ReferralError) as exc:
        mark_payout_paid(payout.pk, staff_user=staff, reference="   ")
    assert exc.value.code == "reference_required"

    mail.outbox.clear()
    # The mail is enqueued on_commit, which never fires under pytest-django's outer
    # transaction — same reason orders/tests/test_emails.py wraps its sends.
    with django_capture_on_commit_callbacks(execute=True):
        mark_payout_paid(payout.pk, staff_user=staff, reference="GTB/2026/0042")

    payout.refresh_from_db()
    assert payout.status == "paid"
    assert payout.reference == "GTB/2026/0042"
    assert len(mail.outbox) == 1
    assert "•••• 6789" in mail.outbox[0].body, "the full account number never leaves"
    assert "0123456789" not in mail.outbox[0].body

    # `paid` is read off the payout, so it matches what the bank actually sent.
    wallet = next(w for w in balances(ref_user) if w.currency.code == "NGN")
    assert wallet.paid == Decimal("30000.00")


@pytest.mark.django_db
def test_changing_the_payout_account_emails_the_holder_but_the_first_save_does_not(
    django_user_model, django_capture_on_commit_callbacks
):
    ref_user, _profile = referrer(django_user_model)

    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        _with_method(ref_user)
    assert mail.outbox == [], "nothing to warn about on a first save"

    with django_capture_on_commit_callbacks(execute=True):
        save_payout_method(
            ref_user, currency=ngn(), bank_name="Zenith", account_name="AMINA OKORO",
            account_number="9876543210",
        )
    assert len(mail.outbox) == 1
    assert "payout account was changed" in mail.outbox[0].subject


@pytest.mark.django_db
def test_rejecting_emails_the_referrer_the_reason_and_says_the_money_came_back(
    django_user_model, django_capture_on_commit_callbacks
):
    """A rejection the customer only discovers by revisiting a page reads, from their
    side, as the shop quietly keeping the money. The mail carries the reviewer's own
    sentence and the fact that matters most: the balance is available again."""
    ref_user, profile = referrer(django_user_model)
    _with_method(ref_user)
    _earn(django_user_model, ref_user, profile, "300000.00")
    payout = request_payout(ref_user, "NGN", accept_terms=True)
    staff = customer(django_user_model, "staff-reject@toke.test", is_staff=True)

    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        reject_payout(
            payout.pk, staff_user=staff,
            customer_message="The account name does not match your bank records.",
        )

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "The account name does not match your bank records." in body, (
        "the reviewer's own words, not a paraphrase — they are the only one who knows"
    )
    assert "available balance" in body
    # The full account number never leaves in an email, here as anywhere else.
    assert "0123456789" not in body


@pytest.mark.django_db
def test_a_payout_is_paid_in_full_because_withholding_is_zero(django_user_model):
    """Hammed's ruling, 2026-08-15: commission is paid in full. A referrer with ₦30,000
    available receives ₦30,000, not ₦28,500."""
    ref_user, profile = referrer(django_user_model)
    _with_method(ref_user)
    _earn(django_user_model, ref_user, profile, "300000.00")

    payout = request_payout(ref_user, "NGN", accept_terms=True)

    assert payout.amount == Decimal("30000.00")
    assert payout.wht_rate_percent == Decimal("0.00")
    assert payout.wht_amount == Decimal("0.00")
    assert payout.net_amount == payout.amount, "net is what leaves the bank"


@pytest.mark.django_db
def test_the_withholding_rate_is_a_setting_and_is_snapshot_on_the_request(
    django_user_model, settings,
):
    """THE POINT OF BUILDING THE MECHANISM AT ZERO. The tax position is the kind of thing
    an accountant changes; changing it should be an env var, not a migration and a
    rewrite. Snapshot rather than read live, exactly like `Commission.rate_percent`, so a
    later change never re-cuts a request that is already open."""
    settings.REFERRAL_WHT_PERCENT = "5.00"
    ref_user, profile = referrer(django_user_model)
    _with_method(ref_user)
    _earn(django_user_model, ref_user, profile, "300000.00")

    payout = request_payout(ref_user, "NGN", accept_terms=True)

    assert payout.amount == Decimal("30000.00"), "gross is still what they earned"
    assert payout.wht_rate_percent == Decimal("5.00")
    assert payout.wht_amount == Decimal("1500.00")
    assert payout.net_amount == Decimal("28500.00")

    # Moving the setting afterwards must not touch a request already in the queue.
    settings.REFERRAL_WHT_PERCENT = "10.00"
    payout.refresh_from_db()
    assert payout.wht_rate_percent == Decimal("5.00")
    assert payout.net_amount == Decimal("28500.00")


@pytest.mark.django_db
def test_a_blocked_referrer_cannot_request_a_payout(django_user_model):
    ref_user, profile = referrer(django_user_model)
    _with_method(ref_user)
    _earn(django_user_model, ref_user, profile, "300000.00")
    profile.is_blocked = True
    profile.save(update_fields=["is_blocked"])

    with pytest.raises(ReferralError) as exc:
        request_payout(ref_user, "NGN", accept_terms=True)
    assert exc.value.code == "referrer_blocked"


@pytest.mark.django_db
def test_currencies_never_mix(django_user_model):
    """Per-currency wallets, no FX. A GBP balance must not help reach the NGN threshold."""
    ref_user, profile = referrer(django_user_model)
    _with_method(ref_user)
    _earn(django_user_model, ref_user, profile, "100000.00")  # ₦10,000, under threshold

    gbp = Currency.objects.get(code="GBP")
    ReferralAdjustment.objects.create(
        referrer=ref_user, currency=gbp, amount=Decimal("500.00"),
        kind="bonus", reason="test",
    )

    wallets = {w.currency.code: w for w in balances(ref_user)}
    assert wallets["NGN"].available == Decimal("10000.00")
    assert wallets["GBP"].available == Decimal("500.00")
    assert wallets["NGN"].can_request is False

    with pytest.raises(ReferralError) as exc:
        request_payout(ref_user, "NGN", accept_terms=True)
    assert exc.value.code == "below_threshold"


@pytest.mark.django_db
def test_elite_tier_counts_sales_in_a_rolling_window_not_commission(django_user_model):
    ref_user, profile = referrer(django_user_model)
    _earn(django_user_model, ref_user, profile, "150000.00", status="pending")
    _earn(django_user_model, ref_user, profile, "80000.00", status="available",
          buyer_email="b2@x.com")
    # Outside the 90-day window — must not count.
    _earn(django_user_model, ref_user, profile, "500000.00", status="available",
          buyer_email="b3@x.com",
          placed_at=timezone.now() - timezone.timedelta(days=120))

    tier = next(t for t in tier_progress(ref_user) if t.currency.code == "NGN")
    assert tier.qualifying_sales == Decimal("230000.00")  # sales, not the 10% cut
    assert tier.is_elite is True
    assert tier.progress_percent == 100


@pytest.mark.django_db
def test_nothing_available_is_refused_distinctly_from_below_threshold(django_user_model):
    ref_user, _profile = referrer(django_user_model)
    _with_method(ref_user)

    with pytest.raises(ReferralError) as exc:
        request_payout(ref_user, "NGN", accept_terms=True)
    assert exc.value.code == "nothing_to_pay"
    assert not PayoutRequest.objects.exists()
