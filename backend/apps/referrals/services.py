"""Every rule the referral programme has, in one module.

The views and the tasks are thin on purpose: they translate HTTP and scheduling, and
nothing in either of them decides what a commission is worth or whether it may be paid.

── THE FIVE MOMENTS IN A COMMISSION'S LIFE, AND WHO DRIVES THEM ──────────────────────

1. CLICK      the storefront sees `?ref=CODE` and stores it in a cookie for 30 days.
              Nothing here runs; there is no server round-trip for a click in v1.
2. PLACEMENT  `checkout.place_order` calls `attribution_code_for_order()` and stamps the
              result on `Order.referral_code`. Cheap, no money, and it is the LAST
              moment the cookie exists.
3. PAYMENT    `payments.services._fulfil_locked` calls `accrue_for_order()`, which
              writes the `pending` Commission. Guarded — see that function.
4. MATURITY   the nightly `tasks.mature_commissions` stamps `matures_at` from the
              order's shipped event and, 60 days later, flips it to `available`.
5. PAYOUT     the customer calls `request_payout()`; staff later `approve_payout()` /
              `mark_payout_paid()` / `reject_payout()`.

and, cutting across all of them, REVERSAL: `reverse_for_refund()` runs from the refund
path and un-earns whatever the customer sent back.

── THE ONE RULE THAT OUTRANKS EVERYTHING ELSE HERE ───────────────────────────────────

**Nothing in this module may break a payment.** Step 3 runs inside the order row lock in
the money-confirmation path. A commission that fails to accrue is a support ticket and a
backfill; a `mark_paid` that raises is a customer whose money left their bank and whose
order never shipped. `accrue_for_order` is therefore built to swallow its own failures,
and the guard is tested (`tests/test_accrual.py`).
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import Currency
from apps.referrals.models import (
    Commission,
    PayoutMethod,
    PayoutRequest,
    ReferralAdjustment,
    ReferralProfile,
)

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

# Statuses in which an order's goods are genuinely on their way to (or with) the
# customer. A commission only starts its holding clock once the order reaches one of
# these — "fully paid AND SHIPPED" is the published wording, and paying on an order that
# was charged but never dispatched would be paying on a sale that has not happened yet.
SHIPPED_ONWARDS = frozenset({"shipped", "delivered", "completed"})

# Statuses that mean the sale is off. A pending commission on one of these is swept to
# `reversed` rather than left to sit forever looking like future income.
DEAD_ORDER_STATUSES = frozenset({"cancelled", "refunded", "expired"})

# No I, O, 0 or 1. A referral code gets read off a phone screen, typed from a story
# screenshot and dictated over the phone, and those four are where that goes wrong.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# Consumer mailbox providers. Sharing one with your referrer means nothing — see
# `fraud_flags`, where excluding these is the difference between a signal and noise.
_FREE_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "ymail.com",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me", "zoho.com",
})


def q2(amount: Decimal) -> Decimal:
    """Round to two places, half-up — the same rule `checkout.services.totals.q2` uses.

    Restated here rather than imported so this module does not depend on the checkout
    app, but it must not DIVERGE: a commission rounded differently from the order it
    came from is a penny of disagreement per sale, and pennies of disagreement are what
    reconciliation arguments are made of.
    """
    return Decimal(amount).quantize(CENT, rounding=ROUND_HALF_UP)


# --- profiles and codes -------------------------------------------------------------


def _candidate_code(user) -> str:
    """A human-shaped code: the customer's own name, then four random characters.

    The name half is what makes it shareable — "AMINA7K3P" is something a person will
    actually put in a caption, "8F2K9QX1" is not. It is stripped to A-Z (accents,
    spaces and apostrophes all go), capped at 8 characters so the whole code stays
    typeable, and falls back to "TOKE" for an account with no usable name at all
    (migrated rows, email-only signups).

    The four random characters, not a counter, are what make guessing another person's
    code pointless: a counter would make "AMINA1" and "AMINA2" adjacent, and a code is
    the handle money accrues to.
    """
    raw = "".join(ch for ch in (user.first_name or "").upper() if ch.isalpha())[:8]
    stem = raw or "TOKE"
    tail = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
    return f"{stem}{tail}"


def generate_code(user, *, attempts: int = 8) -> str:
    """A code no existing profile holds, compared case-insensitively.

    Retries on collision rather than trusting 32^4; with a shared name stem the birthday
    maths is nothing like as comfortable as the raw keyspace suggests, and eight tries
    costs eight cheap indexed reads in the worst case. Exhausting them raises instead of
    returning a duplicate — `ReferralProfile.code`'s unique constraint would refuse the
    insert anyway, and a clear error beats an IntegrityError from three frames away.
    """
    for _ in range(attempts):
        code = _candidate_code(user)
        if not ReferralProfile.objects.filter(code__iexact=code).exists():
            return code
    raise RuntimeError(f"could not mint a unique referral code for user {user.pk}")


def ensure_profile(user) -> ReferralProfile:
    """This customer's referral profile, creating it if this is the first look.

    LAZY, and that is the whole design. Every registered customer is in the programme,
    so the alternative was a `post_save` signal on User minting a code for every account
    at creation — including the ones that never open the page, and including whatever a
    future import creates. A signal is also the kind of machinery that is forgotten in a
    year and then surprises somebody. Existing accounts are handled by
    `manage.py backfill_referral_codes`, which is explicit and re-runnable.

    Races (two tabs opening the page at once) resolve through `get_or_create`; the
    loser's generated code is simply discarded.
    """
    profile = ReferralProfile.objects.filter(user=user).first()
    if profile is not None:
        return profile
    profile, _ = ReferralProfile.objects.get_or_create(
        user=user, defaults={"code": generate_code(user)}
    )
    return profile


# --- attribution --------------------------------------------------------------------


@dataclass(frozen=True)
class AttributionRefusal:
    """Why a referral code on an order was not honoured. Logged, never shown to the
    buyer — telling a shopper "that is your own code" at checkout is both confusing and
    a way to probe whose code is whose."""

    code: str
    reason: str


def attribution_code_for_order(code: str, buyer) -> str:
    """The code to stamp on an order, or "" if this one earns nothing.

    Called from `place_order` with whatever the storefront's cookie held. Everything
    that can disqualify an attribution is checked HERE, at placement, so that accrual
    (which runs in the payment path and must not do interesting work) has nothing left
    to decide.

    The four refusals:

    * unknown code — a typo, or a code from a deleted account.
    * blocked referrer — `is_blocked` stops new earnings, by design; money already
      earned is untouched, because taking that back needs a human and a reason.
    * SELF-REFERRAL — "purchases made through your own affiliate link are strictly
      prohibited" is published terms. Matched on the user row AND on the email and
      phone, because the obvious dodge is a second account: same phone, same person.
      Not matched on shipping address, deliberately — a referrer's flatmate ordering is
      a legitimate sale, and address-matching would refuse it silently at checkout. That
      signal belongs on the payout review screen, where a human can weigh it.
    * anonymous buyer — cannot happen today (checkout is authenticated) but the guard
      costs a line and the alternative is an AttributeError in the checkout path.

    Returns the UPPERCASED code so `Order.referral_code` matches `ReferralProfile.code`
    byte-for-byte and accrual's lookup does not have to be case-insensitive again.
    """
    code = (code or "").strip().upper()
    if not code:
        return ""

    refusal = _refuse_attribution(code, buyer)
    if refusal is not None:
        # INFO, not WARNING: the overwhelmingly common case is a customer clicking their
        # own link to check that it works, which is not an incident.
        logger.info("referral %s not attributed on checkout: %s", refusal.code, refusal.reason)
        return ""
    return code


def _refuse_attribution(code: str, buyer) -> AttributionRefusal | None:
    if buyer is None or not getattr(buyer, "is_authenticated", False):
        return AttributionRefusal(code, "anonymous buyer")

    profile = (
        ReferralProfile.objects.select_related("user").filter(code__iexact=code).first()
    )
    if profile is None:
        return AttributionRefusal(code, "unknown code")
    if profile.is_blocked:
        return AttributionRefusal(code, "referrer is blocked")
    if profile.user_id == buyer.pk:
        return AttributionRefusal(code, "self-referral (same account)")

    referrer = profile.user
    if referrer.email and referrer.email.lower() == (buyer.email or "").lower():
        return AttributionRefusal(code, "self-referral (same email)")
    # Phone numbers are normalised to E.164 on write (accounts.serializers), so a plain
    # comparison is meaningful. Blank never matches blank — two accounts with no phone
    # are not evidence of anything.
    if referrer.phone and referrer.phone == (buyer.phone or ""):
        return AttributionRefusal(code, "self-referral (same phone)")
    return None


# --- accrual ------------------------------------------------------------------------


def commission_base(order) -> Decimal:
    """The "net sales" a commission is calculated on. Published terms: net of shipping,
    taxes and returns.

    Shipping falls out for free — the base is built from the goods columns and never
    touches `shipping_total`. That also makes it correct for a rest-of-world order whose
    freight is quoted and collected AFTER placement: `grand_total` moves later, this
    does not.

    Tax is the part that needs saying out loud. `compute_totals` derives `tax_total` two
    different ways depending on the market:

      * `prices_include_tax=True` (Nigeria): the displayed price already contains the
        VAT, so `subtotal` contains it too and `tax_total` is the slice sitting inside.
        It has to be SUBTRACTED or the shop pays 10% of the government's money away.
      * `prices_include_tax=False` (GB/US/CA): tax is added on top and was never in
        `subtotal`, so subtracting it would under-pay the referrer.

    Hence the branch. It reads as needless today — every seeded country carries
    `tax_rate_percent = 0.00`, so both arms return the same number — and it is written
    anyway, because the day someone sets Nigeria's VAT to 7.5% is not the day anybody
    will remember that the referral base assumed zero.

    Since the tax settings work (Plan-37), `tax_total` MAY contain a shipping-tax
    slice — markets can opt into `tax_applies_to_delivery` — so the item-attributable
    amount is `tax_total - delivery_tax_total`, and that is what gets subtracted.
    `delivery_tax_total` is 0 for every order placed before the column existed, so old
    orders compute exactly as they always did.

    Returns 0.00 rather than a negative number if a discount somehow exceeds the goods —
    it cannot today (`_coupon_discount` clamps to the subtotal) but a commission is not
    a place to propagate an impossible number.
    """
    net = Decimal(order.subtotal) - Decimal(order.discount_total)
    if order.country.prices_include_tax:
        net -= Decimal(order.tax_total) - Decimal(order.delivery_tax_total)
    return max(q2(net), ZERO)


def _commission_amount(base: Decimal, rate: Decimal) -> Decimal:
    return q2(base * rate / Decimal("100"))


def accrue_for_order(order) -> Commission | None:
    """Write the `pending` commission for a paid, referred order. Returns it, or None.

    ── THIS FUNCTION CANNOT BE ALLOWED TO RAISE, AND HERE IS WHY ────────────────────

    It is called from `payments.services._fulfil_locked`, inside the transaction that
    holds the order's row lock and flips the payment to `succeeded`. An exception out of
    here rolls that back. The customer's card has been charged, the gateway believes the
    sale happened, and our order sits in `pending_payment` until it expires — over a
    referral bookkeeping bug. So every failure is caught, logged at exception level (so
    Sentry raises it) and swallowed.

    That trade is only acceptable because the lost work is RECOVERABLE: the order still
    carries `referral_code`, so `manage.py backfill_referral_commissions` can replay
    every order that should have a commission and does not. A missing commission is a
    correctable bookkeeping gap; a rolled-back payment is not correctable at all.

    ── WHY NOT `on_commit` INSTEAD ─────────────────────────────────────────────────

    Because a callback registered with `transaction.on_commit` that throws is dropped on
    the floor with no retry and no queue — the same loss, minus the Sentry event and
    minus any way to know it happened. Doing the work inline, guarded, with a backfill
    command behind it, is the version that fails loudly and repairs cleanly.

    ── A BARE try/except IS NOT ENOUGH, WHICH IS WHY THE WRITE IS SAVEPOINTED ──────

    Catching a Python exception does NOT undo a database one. When a query fails at the
    DATABASE level (an IntegrityError, a numeric overflow), Postgres aborts the whole
    transaction and Django marks the connection `needs_rollback`; the very next statement
    in `_fulfil_locked` — `payment.save()` — then raises `TransactionManagementError` and
    the payment breaks anyway. The except clause alone would give the appearance of
    safety and none of it. What actually restores the connection is a SAVEPOINT: roll
    back to it, and the outer transaction commits the payment as if this never ran.

    HONEST SCOPE, because this was measured rather than assumed: the one write below is
    `get_or_create`, and Django ALREADY wraps its INSERT in a savepoint internally — so
    on today's code the explicit block changes nothing, and a test that removes it still
    passes. It is here so the property belongs to this function rather than to an
    implementation detail of the ORM method it happens to call: the next write added
    inside this `try` gets the guarantee automatically instead of quietly not having it.
    `tests/test_accrual.py` pins the behaviour (a caller can still write afterwards), not
    the mechanism.

    ── IDEMPOTENCY ─────────────────────────────────────────────────────────────────

    `Commission.order` is a OneToOneField and this uses `get_or_create`, so the gateway
    redelivering a webhook (which they all do) cannot mint a second commission.
    """
    try:
        if not order.referral_code:
            return None

        profile = (
            ReferralProfile.objects.select_related("user")
            .filter(code__iexact=order.referral_code)
            .first()
        )
        if profile is None:
            # The referrer's account was deleted between placement and payment. Nothing
            # to pay, and nothing wrong — log it so a pattern would be visible.
            logger.info(
                "order %s carries referral code %s with no profile — no commission",
                order.number, order.referral_code,
            )
            return None

        rate = Decimal(str(settings.REFERRAL_COMMISSION_PERCENT))
        base = commission_base(order)
        with transaction.atomic():  # savepoint — see the docstring
            commission, created = Commission.objects.get_or_create(
                order=order,
                defaults={
                    "referrer": profile.user,
                    "currency": order.currency,
                    "base_amount": base,
                    "rate_percent": rate,
                    "amount": _commission_amount(base, rate),
                },
            )
        if created:
            logger.info(
                "referral commission %s: %s %s to user %s for order %s",
                commission.pk, commission.amount, commission.currency_id,
                profile.user_id, order.number,
            )
        return commission
    except Exception:  # noqa: BLE001 — see the docstring: this must never break payment
        logger.exception(
            "referral accrual failed for order %s — payment continues, backfill required",
            getattr(order, "number", "<unknown>"),
        )
        return None


# --- reversal -----------------------------------------------------------------------


def reverse_for_refund(order, refunded_total: Decimal) -> None:
    """Un-earn commission in proportion to what the customer got back.

    Called from `payments.refunds.apply_succeeded_refund`, which is the single choke
    point every refund passes through — full or partial, staff-initiated or settled by a
    gateway webhook — while it holds the order row lock.

    ── WHY IT TAKES THE RUNNING TOTAL, NOT THE ONE REFUND ──────────────────────────

    `refunded_total` is the sum of every succeeded refund on the order so far, so this
    recomputes the commission from scratch each time rather than decrementing it. That
    makes it idempotent: a redelivered refund webhook recomputes the same number instead
    of subtracting twice, which a decrementing version would do silently and nobody
    would notice until a referrer complained about a balance that only ever went down.

    ── THE THREE CASES ─────────────────────────────────────────────────────────────

    still pending/available, fully refunded  -> `reversed`. Money never left; nothing
                                                more to do.
    still pending/available, partly refunded -> the row is rewritten downward on the
                                                surviving base.
    ALREADY PAID                             -> the row is left exactly as it is and the
                                                shortfall becomes a NEGATIVE
                                                `ReferralAdjustment`. This is the case
                                                the adjustment table exists for: the
                                                money is in someone's bank account and
                                                cannot be recalled, so it nets against
                                                what they earn next. Rewriting the paid
                                                row instead would make the PayoutRequest
                                                it belongs to stop adding up.

    Swallows its own failures for the same reason `accrue_for_order` does: this runs in
    the refund transaction, and a referral bug must not stop a customer being refunded.

    ── IT OPENS ITS OWN ATOMIC BLOCK, AND THAT IS NOT REDUNDANT ────────────────────

    `apply_succeeded_refund` already holds one, so this nests — which in Django means a
    SAVEPOINT, not a second transaction. Two things fall out of that, both wanted:

    1. `select_for_update()` below is legal wherever this is called from. Without the
       block it raises `TransactionManagementError` outside a transaction, and because
       every failure here is caught and logged, that raise would be SILENT — the refund
       would succeed and the commission would quietly never be reversed. Found by
       running the walkthrough script rather than the test suite, which could not catch
       it: pytest-django wraps every test in a transaction, so the missing one was
       invisible under test and only real in production-shaped calls (a management
       command, a shell session, a future caller that does not lock first).
    2. A failure in here rolls back only this savepoint. The customer's refund, in the
       outer transaction, still commits.
    """
    try:
        with transaction.atomic():
            _reverse_locked(order, refunded_total)
    except Exception:  # noqa: BLE001 — a referral bug must not stop a refund
        logger.exception(
            "referral reversal failed for order %s — refund continues, manual correction required",
            getattr(order, "number", "<unknown>"),
        )


def refunded_total_for(order) -> Decimal:
    """Every succeeded refund against this order, summed. The ledger, not a parameter.

    Exists so the recompute below can be called by things that have no refund in hand —
    the nightly sweep, and the payout-release path — and still arrive at the same answer
    the refund webhook would. One source of truth for "how much has gone back".
    """
    from apps.payments.models import Refund

    total = Refund.objects.filter(
        payment__order=order, status="succeeded"
    ).aggregate(s=Sum("amount"))["s"]
    return q2(total or ZERO)


def _surviving_base(order, refunded: Decimal) -> Decimal:
    """The commission base left after `refunded` has gone back to the customer.

    ── THE TAX BUG THIS EXISTS TO NOT HAVE ─────────────────────────────────────────

    A refund amount is GROSS: the customer gets the VAT back too. The commission base is
    NET: `commission_base` strips the embedded tax in markets where `prices_include_tax`.
    Subtracting one from the other directly — which the first version of this did —
    under-pays the referrer by the tax fraction on every partial refund of a
    tax-inclusive order. Worked example at 7.5% VAT: goods ₦10,750 gross → base ₦10,000
    → commission ₦1,000. Half returned, ₦5,375 gross. Naive: base ₦4,625, commission
    ₦462.50. Correct: ₦500. Systematic, in the shop's favour, and exactly the sort of
    thing a ₦200k Club affiliate reconciles and complains about.

    So the arithmetic is done in GROSS space and mapped back to NET at the end, which is
    the same scaling `commission_base` applied on the way in.

    ── SHIPPING, AND WHAT IS KNOWINGLY APPROXIMATE ─────────────────────────────────

    A refund is taken against the whole order, and `payments.Refund` carries a free-text
    `reason` rather than a type — so there is no reliable way to tell "returned goods"
    from "goodwill refund of the delivery fee". Refunds are therefore attributed to the
    GOODS first, capped at the goods total.

    That is deliberately the conservative direction (it reduces commission faster than
    the alternatives), and it has a known wart: a pure shipping refund on an otherwise
    intact sale does cut commission, which sits awkwardly beside "commission excludes
    shipping". Accepted knowingly rather than papered over — the honest fix needs typed
    refunds, and inventing a type here would be inventing precision this data does not
    have. If refund typing ever lands, this is the one function to change.
    """
    gross_goods = q2(Decimal(order.subtotal) - Decimal(order.discount_total))
    net_goods = commission_base(order)
    if gross_goods <= ZERO:
        return ZERO
    refunded_to_goods = min(max(q2(refunded), ZERO), gross_goods)
    surviving_gross = gross_goods - refunded_to_goods
    return q2(net_goods * surviving_gross / gross_goods)


def _reverse_locked(order, refunded_total: Decimal) -> None:
    """The body of `reverse_for_refund`, assuming a transaction and free to raise.

    THE SINGLE RECOMPUTE. Every path that can change what an order owes a referrer —
    the refund webhook, the nightly sweep, releasing a rejected payout's commissions —
    routes through here, and all three pass the SAME running total from the refund
    ledger. Separate implementations were the alternative and they drift: one reduces the
    commission in place while another mints a clawback for the same money, and the
    referrer is docked twice.
    """
    commission = Commission.objects.select_for_update().filter(order=order).first()
    if commission is None:
        return

    refunded = q2(Decimal(refunded_total))
    # A dead order owes nothing regardless of what the refund ledger says: an order can be
    # cancelled with no refund row at all (it never captured money), and an expired one
    # never shipped. Treated as a full reversal.
    dead = order.status in DEAD_ORDER_STATUSES
    surviving_base = ZERO if dead else _surviving_base(order, refunded)
    new_amount = _commission_amount(surviving_base, commission.rate_percent)

    if commission.status == "reversed":
        return  # already fully un-earned; a later partial refund changes nothing
    if commission.status == "paid":
        # Claimed by a payout (or already sent). The row is frozen — rewriting it would
        # make the PayoutRequest it belongs to stop adding up — so the shortfall becomes
        # a negative adjustment instead.
        _claw_back(commission, new_amount, order, dead=dead)
        return

    # Not claimed by any payout, so any clawback minted while it WAS claimed (a payout
    # that has since been rejected) is stale: the reduction is about to be applied to the
    # row itself, and leaving the adjustment would take the same money twice.
    _void_clawback(commission.referrer_id, order)

    if surviving_base <= ZERO:
        commission.status = "reversed"
        commission.reversed_at = timezone.now()
        commission.reversed_reason = (
            f"order is {order.status}" if dead
            else f"order fully refunded ({refunded} {commission.currency_id})"
        )
        # `base_amount` and `amount` are LEFT AS THEY WERE, not zeroed. `reversed` already
        # excludes the row from every balance (see `balances`), so zeroing buys nothing —
        # and it costs the referrer the only record of what the order had been worth. The
        # activity feed renders a reversed row struck through, which says "you earned
        # ₦6,000 and then it came back"; struck-through ₦0.00 says nothing at all. Same
        # choice `tasks._reverse_dead_orders` makes, for the same reason.
        commission.save(update_fields=[
            "status", "reversed_at", "reversed_reason", "updated_at",
        ])
        logger.info("referral commission %s reversed: order %s refunded", commission.pk, order.number)
        return

    if new_amount != commission.amount:
        commission.base_amount = surviving_base
        commission.amount = new_amount
        commission.save(update_fields=["base_amount", "amount", "updated_at"])
        logger.info(
            "referral commission %s reduced to %s after partial refund on order %s",
            commission.pk, new_amount, order.number,
        )


def recompute_for_order(order) -> None:
    """Re-derive what this order owes, from the refund ledger and the order's status.

    The entry point for every caller that does NOT have a refund amount in hand: the
    nightly sweep, and `reject_payout` releasing commissions back. Reads the running
    refund total itself and hands it to the one recompute, so a sweep and a webhook
    arriving in either order converge on the same numbers.

    Idempotent and safe to call on anything. Like `reverse_for_refund` it never raises.
    """
    reverse_for_refund(order, refunded_total_for(order))


def _void_clawback(referrer_id: int, order) -> None:
    """Delete the clawback for this order, if one exists.

    Called when a commission stops being claimed by a payout (a rejected request), at
    which point the reduction belongs on the commission row itself. THE BUG THIS PREVENTS,
    because it is four steps deep and nobody would find it by reading: commission claimed
    by a payout → refund lands → clawback minted (the row is `paid`, so it cannot be
    rewritten) → payout rejected → commission released to `available` at its FULL original
    amount, with the clawback still sitting there. The next recompute then reduces the row
    as well, and the referrer is docked the same refund twice.

    Deleted rather than zeroed: this adjustment records a state that turned out not to
    have happened, and a ₦0.00 "clawback" line in a referrer's history explains nothing.
    """
    ReferralAdjustment.objects.filter(
        referrer_id=referrer_id, order=order, kind="clawback", settled_by__isnull=True
    ).delete()


def _claw_back(commission: Commission, new_amount: Decimal, order, *, dead: bool = False) -> None:
    """Record the shortfall on an ALREADY-PAID commission as a negative adjustment.

    Deduplicated on the order: a redelivered webhook must not stack clawbacks. The
    existing row is rewritten to the new shortfall rather than a second one added, so
    two partial refunds on the same order settle at the right total.

    A clawback that has already been SETTLED by a later payout is left alone and a new
    one is written beside it — netting the same money out of a payout that has already
    gone would silently forgive it.
    """
    shortfall = q2(commission.amount - new_amount)
    if shortfall <= ZERO:
        return
    # UNSETTLED only. One already netted into a payout that has gone out is history and
    # must not be rewritten — reducing it would hand back money the shop has recovered,
    # and raising it would net the same loss twice.
    existing = ReferralAdjustment.objects.filter(
        referrer=commission.referrer, order=order, kind="clawback", settled_by__isnull=True
    ).first()
    already_settled = q2(
        ReferralAdjustment.objects.filter(
            referrer=commission.referrer, order=order, kind="clawback",
            settled_by__isnull=False,
        ).aggregate(s=Sum("amount"))["s"] or ZERO
    )
    # What is still owed after whatever past payouts have already clawed back. Negative
    # `already_settled` means money recovered, so this ADDS it back to the outstanding
    # shortfall rather than subtracting.
    shortfall = q2(shortfall + already_settled)
    if shortfall <= ZERO:
        _void_clawback(commission.referrer_id, order)
        return
    reason = (
        f"order {order.number} {'cancelled' if dead else 'refunded'} after commission "
        f"was paid out (payout {commission.payout_id or '—'})"
    )
    if existing is not None:
        if existing.amount != -shortfall:
            existing.amount = -shortfall
            existing.reason = reason
            existing.save(update_fields=["amount", "reason", "updated_at"])
        return
    ReferralAdjustment.objects.create(
        referrer=commission.referrer, currency=commission.currency,
        amount=-shortfall, kind="clawback", reason=reason, order=order,
    )
    logger.info(
        "referral clawback %s %s against user %s for order %s (already paid out)",
        shortfall, commission.currency_id, commission.referrer_id, order.number,
    )


# --- balances and stats -------------------------------------------------------------


@dataclass(frozen=True)
class Wallet:
    """One currency's worth of a referrer's money. Everything is derived; nothing here
    is stored, and `services.balances` is the only thing that builds one."""

    currency: Currency
    available: Decimal    # payable right now (matured, minus adjustments)
    pending: Decimal      # earned, still inside the holding period
    paid: Decimal         # settled through past payouts
    lifetime: Decimal     # everything ever genuinely earned
    threshold: Decimal    # minimum before a payout may be requested
    open_request: PayoutRequest | None

    @property
    def can_request(self) -> bool:
        """Threshold met, nothing already in flight, and not in the red.

        The negative check is not redundant with the threshold check: a clawback can
        push a wallet below zero, and `available >= threshold` is false there anyway —
        but stating it separately is what lets the API explain WHY, and "your balance is
        negative after a return" is a very different message from "keep going".
        """
        return (
            self.open_request is None
            and self.available > ZERO
            and self.available >= self.threshold
        )


def threshold_for(currency_code: str) -> Decimal | None:
    """The payout minimum for a currency, or None if the shop does not pay it out.

    None is not an error state: it means nobody has decided what a payout in that
    currency looks like, and refusing is safer than inventing a number.
    """
    return settings.REFERRAL_PAYOUT_THRESHOLDS.get(currency_code)


def _sum(queryset, field: str = "amount") -> Decimal:
    return queryset.aggregate(s=Sum(field))["s"] or ZERO


def balances(user) -> list[Wallet]:
    """Every currency this referrer has money in, richest first.

    Built from four aggregate queries over the whole ledger rather than per currency:
    the number of currencies is four, but the number of QUERIES should not scale with it
    at all, and a per-currency loop is how an N+1 arrives on a page that renders on
    every account visit.

    A currency appears if it has ANY history — including one that only holds a clawback,
    because a referrer whose balance went negative must be able to see that it did.
    """
    commissions = Commission.objects.filter(referrer=user)
    adjustments = ReferralAdjustment.objects.filter(referrer=user)

    by_currency: dict[str, dict[str, Decimal]] = {}

    def bucket(code: str) -> dict[str, Decimal]:
        return by_currency.setdefault(
            code, {"available": ZERO, "pending": ZERO, "paid": ZERO, "lifetime": ZERO}
        )

    for row in commissions.values("currency_id", "status").annotate(total=Sum("amount")):
        b = bucket(row["currency_id"])
        total = row["total"] or ZERO
        if row["status"] == "available":
            b["available"] += total
            b["lifetime"] += total
        elif row["status"] == "pending":
            b["pending"] += total
        elif row["status"] == "paid":
            b["lifetime"] += total
        # `reversed` contributes to nothing — it was never earned.

    # Only UNSETTLED adjustments move the balance; one already netted into a past payout
    # has done its work (see ReferralAdjustment.settled_by).
    unsettled = adjustments.filter(settled_by__isnull=True)
    for row in unsettled.values("currency_id").annotate(total=Sum("amount")):
        bucket(row["currency_id"])["available"] += row["total"] or ZERO

    # EVERY adjustment counts towards lifetime, credits and clawbacks alike, settled or
    # not. Counting only credits was path-dependent and therefore wrong: two economically
    # identical returns diverged depending on WHEN they landed. A return before payout
    # flips the commission to `reversed` and it drops out of lifetime; the same return
    # after payout leaves the commission `paid` and counted, so ignoring the clawback left
    # lifetime permanently overstating by the refunded amount. Netting the adjustment back
    # out makes both roads arrive at the same number.
    #
    # So "earned all time" means net of returns. That is the honest reading of earnings
    # and it agrees with `paid` + `available` + `pending` over a referrer's whole history.
    for row in adjustments.values("currency_id").annotate(total=Sum("amount")):
        bucket(row["currency_id"])["lifetime"] += row["total"] or ZERO

    # `paid` is what actually LEFT, read off the payout requests rather than summed from
    # commissions: a payout that netted a clawback sent less than its commissions add up
    # to, and the number a referrer checks against their bank statement has to be the
    # one that was transferred.
    for row in (
        PayoutRequest.objects.filter(referrer=user, status="paid")
        .values("currency_id").annotate(total=Sum("amount"))
    ):
        bucket(row["currency_id"])["paid"] += row["total"] or ZERO

    open_requests = {
        r.currency_id: r
        for r in PayoutRequest.objects.filter(
            referrer=user, status__in=("requested", "approved")
        ).select_related("currency")
    }

    currencies = {c.code: c for c in Currency.objects.filter(code__in=by_currency)}
    wallets = [
        Wallet(
            currency=currencies[code],
            available=q2(b["available"]),
            pending=q2(b["pending"]),
            paid=q2(b["paid"]),
            lifetime=q2(b["lifetime"]),
            threshold=threshold_for(code) or ZERO,
            open_request=open_requests.get(code),
        )
        for code, b in by_currency.items()
        if code in currencies
    ]
    wallets.sort(key=lambda w: (-w.lifetime, w.currency.code))
    return wallets


@dataclass(frozen=True)
class Tier:
    """₦200k Club progress in one currency. Computed on every read — see the settings
    comment for why there is no stored tier."""

    currency: Currency
    qualifying_sales: Decimal
    threshold: Decimal
    window_days: int

    @property
    def is_elite(self) -> bool:
        return self.qualifying_sales >= self.threshold

    @property
    def progress_percent(self) -> int:
        """0-100, for a progress bar. Capped, because a bar past 100% looks broken."""
        if self.threshold <= ZERO:
            return 100
        pct = (self.qualifying_sales / self.threshold) * 100
        return min(100, int(pct))


def tier_progress(user) -> list[Tier]:
    """Rolling-window qualifying sales per currency the tier is defined in.

    Counts `base_amount` (the net sale), not the commission — the published tier is
    "generate over ₦200,000 in SALES", which is the referrer's output, not their cut.

    Reversed commissions are excluded: a sale that came back was not generated. Pending
    ones are INCLUDED, because the tier is about sales driven, not money released, and
    making a referrer wait 60 days to see credit for a sale they made would read as the
    programme not counting their work.

    The window runs from the order's placement, so a referrer's 90 days is 90 days of
    selling and not 90 days of our fulfilment speed.
    """
    since = timezone.now() - timezone.timedelta(days=settings.REFERRAL_ELITE_WINDOW_DAYS)
    codes = list(settings.REFERRAL_ELITE_THRESHOLDS)
    rows = (
        Commission.objects.filter(
            referrer=user, currency_id__in=codes, order__placed_at__gte=since
        )
        .exclude(status="reversed")
        .values("currency_id")
        .annotate(total=Sum("base_amount"))
    )
    totals = {r["currency_id"]: r["total"] or ZERO for r in rows}
    currencies = {c.code: c for c in Currency.objects.filter(code__in=codes)}
    return [
        Tier(
            currency=currencies[code],
            qualifying_sales=q2(totals.get(code, ZERO)),
            threshold=threshold,
            window_days=settings.REFERRAL_ELITE_WINDOW_DAYS,
        )
        for code, threshold in settings.REFERRAL_ELITE_THRESHOLDS.items()
        if code in currencies
    ]


def referred_customer_count(user) -> int:
    """How many DIFFERENT people have bought through this referrer's link.

    Derived from commissions rather than from a signup table, and that is a deliberate
    narrowing: it counts customers who actually ordered, not visitors who clicked or
    accounts that registered and never bought. A "12 referrals" number that is really
    "12 clicks" is the kind of stat that makes a referrer think the programme is broken
    when their balance says ₦0.
    """
    return (
        Commission.objects.filter(referrer=user)
        .exclude(status="reversed")
        .values("order__user_id")
        .distinct()
        .count()
    )


# --- payout methods -----------------------------------------------------------------


class ReferralError(Exception):
    """Refused. `code` is a stable machine string the storefront maps to copy; `detail`
    is the human sentence. Same shape as `checkout.CheckoutError` so the BFF's error
    handling does not need a second dialect."""

    def __init__(self, code: str, detail: str, http: int = 400):
        self.code, self.detail, self.http = code, detail, http
        super().__init__(detail)


@transaction.atomic
def save_payout_method(user, *, currency: Currency, bank_name: str, account_name: str,
                       account_number: str, bank_code: str = "", extra: dict | None = None):
    """Create or replace this referrer's payout account for one currency.

    Emails the account holder on the FIRST SAVE and on every CHANGE — two different
    templates, because they are two different sentences. This is the control that turns
    an account-takeover payout redirect from silent into noisy; see `PayoutMethod`'s
    docstring for why it, rather than encryption, is where the effort went.

    The add-email was originally omitted ("there is nothing to warn about yet") and the
    2026-08-15 review reversed that: the first save is exactly the takeover window. A
    victim with accrued earnings and NO account on file heard nothing when a hijacker
    added one — the first email they ever got was "you've been paid". What stays true
    from the original reasoning is that a no-op resave sends nothing: an alert that
    fires when nothing happened trains people to ignore the one that matters.
    """
    existing = PayoutMethod.objects.filter(user=user, currency=currency).first()
    changed = existing is not None and (
        existing.account_number != account_number
        or existing.bank_name != bank_name
        or existing.account_name != account_name
    )
    method, _ = PayoutMethod.objects.update_or_create(
        user=user, currency=currency,
        defaults={
            "bank_name": bank_name, "account_name": account_name,
            "account_number": account_number, "bank_code": bank_code,
            "extra": extra or {},
        },
    )
    if existing is None or changed:
        from apps.referrals.emails import (
            enqueue_payout_method_added,
            enqueue_payout_method_changed,
        )

        notify = enqueue_payout_method_added if existing is None else enqueue_payout_method_changed
        transaction.on_commit(lambda: notify(method.pk))
    return method


# --- payout requests ----------------------------------------------------------------


@transaction.atomic
def request_payout(user, currency_code: str, *, accept_terms: bool = False) -> PayoutRequest:
    """Claim this referrer's available balance in one currency.

    ── WHAT "CLAIM" MEANS, AND WHY IT IS A WRITE ───────────────────────────────────

    Every `available` commission in that currency is pointed at the new request and
    moved to `paid` in the same transaction. The word is doing work: the balance is
    DERIVED from those rows, so if they stayed `available` the customer could open a
    second request for the same money from a second tab. Re-labelling them is what makes
    the balance drop to zero and the double-request impossible, with no lock and no
    "pending payout" column to keep in step.

    The honest wart: they say `paid` from the moment of the request, while the money
    does not move until staff send it. `PayoutRequest.status` is the truth about the
    money; `Commission.status` is the truth about whether the row is still claimable.
    Rejecting a request puts them back (`reject_payout`).

    ── THE TERMS GATE ──────────────────────────────────────────────────────────────

    Auto-enrolment means nobody ever agreed to anything, so the first payout request is
    where agreement is collected. Refused rather than assumed: the clauses that matter
    in a dispute (no self-referral, clawback on returns) are exactly the ones a referrer
    would deny having seen, and the cost of collecting it is one checkbox.
    """
    currency = Currency.objects.filter(code=currency_code, is_active=True).first()
    if currency is None:
        raise ReferralError("currency_unknown", "That currency is not available.")

    profile = ensure_profile(user)
    if profile.is_blocked:
        raise ReferralError(
            "referrer_blocked",
            "Payouts are on hold for this account. Please contact support.",
            http=403,
        )

    if not profile.terms_accepted_at:
        if not accept_terms:
            raise ReferralError(
                "terms_required",
                "Please accept the affiliate programme terms before requesting a payout.",
            )
        profile.terms_accepted_at = timezone.now()
        profile.terms_version = settings.REFERRAL_TERMS_VERSION
        profile.save(update_fields=["terms_accepted_at", "terms_version", "updated_at"])

    method = PayoutMethod.objects.filter(user=user, currency=currency).first()
    if method is None:
        raise ReferralError(
            "payout_method_required",
            f"Add the bank account you want your {currency.code} payouts sent to.",
        )

    if PayoutRequest.objects.filter(
        referrer=user, currency=currency, status__in=("requested", "approved")
    ).exists():
        raise ReferralError(
            "payout_already_open",
            "You already have a payout being processed for this currency.",
            http=409,
        )

    threshold = threshold_for(currency.code)
    if threshold is None:
        raise ReferralError(
            "currency_not_payable", f"{currency.code} balances cannot be paid out yet."
        )

    # Locked, because this is the read the amount is frozen from: without the lock two
    # concurrent requests could both see the same available rows and both claim them.
    claimed = list(
        Commission.objects.select_for_update()
        .filter(referrer=user, currency=currency, status="available")
    )
    unsettled = list(
        ReferralAdjustment.objects.select_for_update()
        .filter(referrer=user, currency=currency, settled_by__isnull=True)
    )
    adjustments = q2(sum((a.amount for a in unsettled), ZERO))
    amount = q2(sum((c.amount for c in claimed), ZERO) + adjustments)

    if amount <= ZERO:
        raise ReferralError("nothing_to_pay", "There is nothing available to withdraw yet.")
    if amount < threshold:
        raise ReferralError(
            "below_threshold",
            f"You need at least {threshold} {currency.code} to request a payout. "
            "Your balance rolls over until then.",
        )

    # Withholding, snapshot at request time. Zero by ruling (see
    # `settings.REFERRAL_WHT_PERCENT`), which makes `net_amount == amount` today — the
    # arithmetic is written out anyway so that changing one env var changes what the
    # shop sends, rather than requiring anybody to find every place a payout is summed.
    wht_rate = Decimal(settings.REFERRAL_WHT_PERCENT)
    wht_amount = q2(amount * wht_rate / Decimal("100"))
    request = PayoutRequest.objects.create(
        referrer=user, currency=currency, amount=amount,
        wht_rate_percent=wht_rate,
        wht_amount=wht_amount,
        net_amount=q2(amount - wht_amount),
        method_snapshot=method.snapshot(),
    )
    Commission.objects.filter(pk__in=[c.pk for c in claimed]).update(
        status="paid", payout=request, updated_at=timezone.now()
    )
    # The adjustments were netted into `amount`, so they are settled by this request
    # too — leaving them unlinked would net the same clawback into every future payout.
    ReferralAdjustment.objects.filter(pk__in=[a.pk for a in unsettled]).update(
        settled_by=request, updated_at=timezone.now()
    )

    logger.info(
        "payout request %s: %s %s for user %s (%s commissions)",
        request.pk, amount, currency.code, user.pk, len(claimed),
    )
    return request


@transaction.atomic
def reject_payout(request_id: int, *, staff_user, customer_message: str, admin_note: str = ""):
    """Refuse a request and RELEASE its commissions back to `available`.

    The release is the whole point. A rejected request that left its commissions marked
    `paid` would strand the referrer's money permanently: their balance would read zero
    for ever with no row explaining it, and the only fix would be a hand-written SQL
    update. Rejection has to be reversible or it is a data-loss button.
    """
    req = PayoutRequest.objects.select_for_update().get(pk=request_id)
    # `approved` is rejectable too, not just `requested`. Approval only means "we mean to
    # send this"; the money leaves by hand days later, so the two things that happen in
    # that gap both need a way back — a transfer the bank bounced, and fraud noticed after
    # someone clicked approve. Without this an approved request can only ever go to `paid`,
    # so the only way to undo one is a hand-written SQL update, which is exactly what
    # rejection exists to avoid. `paid` is NOT rejectable: money has left, and reversing
    # that is a clawback (`ReferralAdjustment`), not a status change.
    if req.status not in ("requested", "approved"):
        raise ReferralError("payout_not_open", "That request is no longer open.", http=409)
    req.status = "rejected"
    req.decided_at = timezone.now()
    req.decided_by = staff_user
    req.customer_message = customer_message
    req.admin_note = admin_note
    req.save(update_fields=[
        "status", "decided_at", "decided_by", "customer_message", "admin_note", "updated_at",
    ])
    released = list(req.commissions.select_related("order").all())
    req.commissions.update(status="available", payout=None, updated_at=timezone.now())
    # The netted adjustments come back too, or a rejected request would quietly forgive
    # a clawback — the one direction of this bug that costs the shop money.
    req.adjustments.update(settled_by=None, updated_at=timezone.now())

    # A released commission is claimable again, so anything that happened to its order
    # while it was frozen has to be applied to the ROW now rather than left as a
    # clawback beside it. Recomputing each one from the refund ledger does exactly that
    # and voids the stale adjustment (see `_void_clawback`). Without this, a refund that
    # landed during the review window is charged twice: once as the surviving clawback,
    # once when the next recompute reduces the released row.
    for commission in released:
        recompute_for_order(commission.order)

    # AFTER the release, and on_commit: the mail says "the money is back in your
    # available balance", and that sentence must not be able to go out ahead of the
    # rows that make it true — nor at all if this transaction rolls back.
    from apps.referrals.emails import enqueue_payout_rejected

    transaction.on_commit(lambda: enqueue_payout_rejected(req.pk))
    return req


@transaction.atomic
def approve_payout(request_id: int, *, staff_user, admin_note: str = ""):
    """Staff mean to send this. Distinct from paid — see PayoutRequest's docstring."""
    req = PayoutRequest.objects.select_for_update().get(pk=request_id)
    if req.status != "requested":
        raise ReferralError("payout_not_open", "That request is no longer open.", http=409)
    req.status = "approved"
    req.decided_at = timezone.now()
    req.decided_by = staff_user
    req.admin_note = admin_note
    req.save(update_fields=["status", "decided_at", "decided_by", "admin_note", "updated_at"])
    return req


@transaction.atomic
def mark_payout_paid(request_id: int, *, staff_user, reference: str, admin_note: str = ""):
    """The transfer left the bank. `reference` is the bank's, and it is REQUIRED: it is
    the only thing that settles "I never received it", and a payout marked paid with no
    reference is an assertion nobody can check."""
    if not reference.strip():
        raise ReferralError("reference_required", "Record the bank transfer reference.")
    req = PayoutRequest.objects.select_for_update().get(pk=request_id)
    if req.status not in ("requested", "approved"):
        raise ReferralError("payout_not_open", "That request is no longer open.", http=409)
    req.status = "paid"
    req.paid_at = timezone.now()
    req.reference = reference.strip()
    req.decided_by = req.decided_by or staff_user
    req.decided_at = req.decided_at or timezone.now()
    if admin_note:
        req.admin_note = admin_note
    req.save(update_fields=[
        "status", "paid_at", "reference", "decided_by", "decided_at", "admin_note", "updated_at",
    ])
    from apps.referrals.emails import enqueue_payout_paid

    transaction.on_commit(lambda: enqueue_payout_paid(req.pk))
    return req


# --- blocking, and manual corrections -----------------------------------------------


@transaction.atomic
def set_referrer_blocked(user, *, blocked: bool, reason: str, staff_user) -> ReferralProfile:
    """Stop (or resume) a referrer earning. The whole of the abuse response for v1.

    ── WHAT BLOCKING DOES AND, MORE IMPORTANTLY, DOES NOT DO ───────────────────────

    It stops NEW commissions accruing (`_refuse_attribution` refuses the code at
    checkout) and stops new payout requests (`request_payout` raises
    `referrer_blocked`). It does NOT touch money already earned, and that restraint is
    deliberate: taking earned money back is `ReferralAdjustment`'s job, it requires
    somebody to type a reason, and it leaves a signed row behind. A block that silently
    zeroed a balance would be the same destructive act with no audit trail and no
    reversal.

    It also does not touch an OPEN payout request. If a referrer is blocked mid-review,
    the request is still sitting in the queue and a human still has to decide it —
    rejecting it is one click and releases the money, which is the honest sequence.
    Auto-rejecting here would bury a money decision inside an abuse action.

    A reason is REQUIRED to block and ignored to unblock. Blocking is the destructive
    direction and "why is this person blocked" is the question somebody will ask in six
    months, most likely a different person; unblocking needs no justification because it
    restores the default.
    """
    profile = ReferralProfile.objects.select_for_update().filter(user=user).first()
    if profile is None:
        profile = ensure_profile(user)
        profile = ReferralProfile.objects.select_for_update().get(pk=profile.pk)
    if blocked and not reason.strip():
        raise ReferralError("reason_required", "Say why this referrer is being blocked.")
    profile.is_blocked = blocked
    profile.blocked_reason = reason.strip() if blocked else ""
    profile.save(update_fields=["is_blocked", "blocked_reason", "updated_at"])
    logger.info(
        "referral profile %s %s by %s",
        profile.code, "blocked" if blocked else "unblocked", getattr(staff_user, "pk", None),
    )
    return profile


@transaction.atomic
def add_adjustment(
    referrer, *, currency: Currency, amount: Decimal, kind: str, reason: str, staff_user
) -> ReferralAdjustment:
    """Move a referrer's balance by hand, in one currency, with a reason attached.

    The signed amount IS the interface — negative takes money away, positive gives it.
    Not an unsigned amount plus a direction, for the reason `ReferralAdjustment.amount`
    already gives: a sum that has to consult a flag is a sum somebody gets backwards.

    ── WHY THIS DELIBERATELY REFUSES ALMOST NOTHING ────────────────────────────────

    A manual adjustment is the escape hatch for the cases the model did not anticipate —
    a goodwill payment, a ₦200k Club retainer, a correction after a support call, money
    owed from the WordPress programme. Validation that second-guesses the human defeats
    the purpose. So the only refusals are the ones that would corrupt the ledger rather
    than merely be unwise: a zero amount (a row that changes nothing but implies
    something happened), a missing reason, and a currency the shop cannot pay out at all
    — a balance in a currency with no threshold can never be withdrawn, so crediting one
    creates money the referrer can see and never receive.

    NOT refused, on purpose: a negative adjustment larger than the current balance. The
    balance is allowed to go negative (see `ReferralAdjustment`'s docstring — a clawback
    after a payout does exactly this) and `request_payout` already refuses while it is.
    Clamping here would silently forgive the remainder, which is the one direction of
    this bug that costs the shop money.
    """
    amount = q2(Decimal(amount))
    if amount == ZERO:
        raise ReferralError("amount_required", "An adjustment of zero changes nothing.")
    if not reason.strip():
        raise ReferralError("reason_required", "Say why — this row outlives everyone here.")
    if threshold_for(currency.code) is None:
        raise ReferralError(
            "currency_not_payable",
            f"The shop does not pay out {currency.code}, so a {currency.code} balance "
            f"could never be withdrawn.",
        )
    adjustment = ReferralAdjustment.objects.create(
        referrer=referrer, currency=currency, amount=amount, kind=kind,
        reason=reason.strip(), created_by=staff_user,
    )
    logger.info(
        "referral adjustment %s: %s %s for user %s by %s (%s)",
        adjustment.pk, amount, currency.code, referrer.pk,
        getattr(staff_user, "pk", None), kind,
    )
    return adjustment


# --- fraud signals (read by the admin payout queue) ---------------------------------


def fraud_flags(request: PayoutRequest) -> list[str]:
    """Human-readable reasons a payout deserves a second look, worst first.

    NOT a score and NOT a block. Manual monthly review is this programme's main fraud
    control (there is no device fingerprinting and no velocity model), so the job here
    is to put the three or four things a person would want to notice in front of them
    rather than to make the decision for them.

    Shipping-address matching lives HERE rather than in `attribution_code_for_order`
    deliberately: a referrer's flatmate ordering is a real sale, so refusing it silently
    at checkout would be wrong, while showing a reviewer "every order shipped to the
    referrer's own address" is exactly the signal they need.
    """
    flags: list[str] = []
    commissions = list(
        request.commissions.select_related("order").only(
            "order__shipping_address", "order__user_id", "order__email"
        )
    )
    if not commissions:
        return flags

    referrer_addresses = {
        _address_key(a)
        for a in request.referrer.addresses.all()
    }
    same_address = sum(
        1 for c in commissions
        if _address_key_from_snapshot(c.order.shipping_address) in referrer_addresses
    )
    if same_address:
        flags.append(
            f"{same_address} of {len(commissions)} orders shipped to the referrer's own address"
        )

    buyers = {c.order.user_id for c in commissions}
    if len(buyers) == 1 and len(commissions) > 2:
        flags.append(f"all {len(commissions)} orders came from a single customer")

    domains = {
        (c.order.email or "").split("@")[-1].lower() for c in commissions if c.order.email
    }
    referrer_domain = (request.referrer.email or "").split("@")[-1].lower()
    # Free providers excluded, or this fires on almost every genuine Nigerian referrer:
    # a shared @gmail.com is not a signal, it is the base rate. A shared PRIVATE domain
    # (a company, a family domain) is worth a second look — which is what this is for.
    if (
        referrer_domain
        and referrer_domain not in _FREE_EMAIL_DOMAINS
        and domains == {referrer_domain}
    ):
        flags.append(f"every buyer shares the referrer's email domain ({referrer_domain})")

    if request.referrer.date_joined > request.created_at - timezone.timedelta(days=30):
        flags.append("referrer account is less than 30 days old")

    # THE ACCOUNT-TAKEOVER SIGNAL. The request carries a snapshot of the bank account as
    # it was when the customer asked, and `mark_payout_paid` pays that snapshot rather
    # than whatever the account says today — so a hijacker who changes the details after a
    # request is in flight does NOT get the money. This flag is the other half of that
    # control: it puts the change in front of the reviewer, because the innocent version
    # (the customer noticed a typo in their own account number) and the hostile version
    # look identical in the data and only a human can tell them apart by asking.
    snapshot = request.method_snapshot or {}
    current = PayoutMethod.objects.filter(
        user=request.referrer, currency=request.currency
    ).first()
    if current and snapshot.get("account_number") and (
        current.account_number != snapshot.get("account_number")
        or current.bank_name != snapshot.get("bank_name")
    ):
        flags.append(
            "bank details were CHANGED after this request was made — paying the snapshot, "
            "not the current account"
        )

    return flags


def _address_key(address) -> str:
    return f"{address.line1.strip().lower()}|{(address.postcode or '').strip().lower()}"


def _address_key_from_snapshot(snapshot: dict) -> str:
    return (
        f"{(snapshot or {}).get('line1', '').strip().lower()}"
        f"|{((snapshot or {}).get('postcode') or '').strip().lower()}"
    )
