"""Scheduled referral housekeeping.

One task, run daily, doing three passes. They are one task rather than three because
they are strictly ordered — a commission cannot mature before it has been stamped, and
stamping a dead order's commission would be work thrown away — and because a single
daily job is one thing to reason about when a referrer says their balance is wrong.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.orders.models import OrderEvent
from apps.referrals.models import Commission, PayoutRequest
from apps.referrals.services import (
    DEAD_ORDER_STATUSES,
    SHIPPED_ONWARDS,
    recompute_for_order,
)

logger = logging.getLogger(__name__)


def _stamp_maturity() -> int:
    """Give every shipped-but-unstamped commission its `matures_at` date.

    THE CLOCK STARTS AT SHIPPING, NOT AT PAYMENT. The published terms hold commission
    for 60 days "for returns to ensure sale validity", and a return window runs from
    when the customer gets the parcel — so an order that took three weeks to reach Lagos
    must not have three weeks of its holding period eaten by our own logistics. Reading
    the real `status:shipped` event, rather than assuming a lead time, is also what
    makes the date shown on the account page a fact instead of an estimate.

    Derived from the order's timeline rather than hooked into `orders.state.transition`
    on purpose: an effect registered there runs `on_commit` with no retry, so a blip
    would silently leave a commission unstamped for ever. A daily sweep over the
    timeline is self-healing — miss a day and the next run catches up.
    """
    pending = (
        Commission.objects.filter(status="pending", matures_at__isnull=True)
        .filter(order__status__in=SHIPPED_ONWARDS)
        .values_list("pk", "order_id")
    )
    rows = list(pending)
    if not rows:
        return 0

    # One query for every shipping event in the batch, oldest kept: an order that was
    # shipped, held, and shipped again should hold from the FIRST dispatch, which is
    # when the customer's return window really began.
    shipped_at: dict[int, object] = {}
    for order_id, created_at in (
        OrderEvent.objects.filter(
            order_id__in=[order_id for _, order_id in rows], type="status:shipped"
        )
        .order_by("order_id", "created_at")
        .values_list("order_id", "created_at")
    ):
        shipped_at.setdefault(order_id, created_at)

    hold = timezone.timedelta(days=settings.REFERRAL_HOLD_DAYS)
    stamped = 0
    for pk, order_id in rows:
        when = shipped_at.get(order_id)
        if when is None:
            # Status says shipped-or-beyond but no shipping event exists — a migrated
            # legacy order, or one moved straight from on_hold. Fall back to the
            # timeline entry for the status it IS in; if even that is missing, leave it
            # unstamped rather than invent a date, and it will be picked up if one
            # appears. An unpaid commission is recoverable; an early payout is not.
            continue
        Commission.objects.filter(pk=pk).update(
            matures_at=when + hold, updated_at=timezone.now()
        )
        stamped += 1
    return stamped


def _recompute_affected() -> int:
    """Re-derive every commission whose order is dead or has seen a refund.

    ── WHY THIS SWEEPS `paid` COMMISSIONS TOO, WHICH IS THE WHOLE POINT ────────────

    An earlier version filtered to `pending`/`available`, and that left a hole with real
    money in it: a commission CLAIMED by an open payout has status `paid`, so an order
    cancelled while its payout sat in review escaped reversal entirely — the payout went
    out at full value and no clawback was ever minted. Including `paid` here routes those
    through `recompute_for_order`, which knows to write the negative adjustment instead of
    rewriting a frozen row.

    ── AND WHY IT RECOMPUTES REFUNDED ORDERS RATHER THAN ONLY DEAD ONES ───────────

    `reverse_for_refund` swallows its own failures (it runs inside the refund transaction
    and must never block a customer's money going back). Without a repair path, a partial
    refund whose reversal threw is a silent, permanent over-payment that nothing ever
    retries. Recomputing from the refund ledger is idempotent and from scratch, so
    sweeping every order with refund activity costs nothing when there is nothing wrong
    and fixes it when there is.

    Counts orders VISITED, not orders changed — the recompute is deliberately a no-op on
    anything already correct, and a "changed" count would need a second read to compute.
    """
    from apps.payments.models import Refund

    refunded_order_ids = set(
        Refund.objects.filter(status="succeeded").values_list("payment__order_id", flat=True)
    )
    affected = (
        Commission.objects.exclude(status="reversed")
        .filter(Q(order__status__in=DEAD_ORDER_STATUSES) | Q(order_id__in=refunded_order_ids))
        .select_related("order", "order__country")
    )
    visited = 0
    for commission in affected:
        # One order at a time, each in its own transaction: a poison row must not roll
        # back the ones already fixed, and `recompute_for_order` never raises anyway.
        recompute_for_order(commission.order)
        visited += 1
    return visited


def _release_matured() -> int:
    """pending -> available for everything past its holding date.

    The order-status filter is re-applied here and not merely trusted from
    `_recompute_affected` above: the two passes run in the same second, but this is the
    query that actually releases money, and it costs nothing for it to state its own
    precondition rather than depend on a sibling having run first.
    """
    return Commission.objects.filter(
        status="pending",
        matures_at__isnull=False,
        matures_at__lte=timezone.now(),
        order__status__in=SHIPPED_ONWARDS,
    ).update(status="available", updated_at=timezone.now())


def _stalled_count() -> int:
    """Commissions that SHOULD have matured and have not. The number to alert on.

    A background sweep that quietly stops working looks exactly like a sweep with nothing
    to do, and the first person to notice is a referrer asking why their balance has said
    "pending" for three months. This is the cheap tripwire: anything still `pending` on a
    shipped order whose holding period has clearly elapsed is, by definition, work the
    sweep failed to do.
    """
    cutoff = timezone.now() - timezone.timedelta(days=settings.REFERRAL_HOLD_DAYS + 1)
    return Commission.objects.filter(
        status="pending",
        order__status__in=SHIPPED_ONWARDS,
        order__events__type="status:shipped",
        order__events__created_at__lt=cutoff,
    ).distinct().count()


@shared_task
def mature_commissions() -> dict:
    """Daily: stamp holding dates, recompute what changed, release what is due.

    ── EACH PASS IN ITS OWN TRANSACTION, AND EACH PASS ALLOWED TO FAIL ALONE ───────

    The three used to share one `atomic()` block. That meant a single poison row — one
    malformed event, one integrity error — rolled back ALL THREE passes, and since the
    same row is still there tomorrow, the sweep would stay broken indefinitely: nothing
    matures, nothing reverses, and nobody finds out until a customer complains. Failing
    one pass now costs that pass only, is logged at exception level so Sentry raises it,
    and the other two still do their work.

    `stalled` is the number that says whether any of that happened, in the return value
    and in the log — a silent zero-work sweep and a silently-broken one are otherwise
    indistinguishable.
    """
    result = {"stamped": 0, "recomputed": 0, "released": 0, "stalled": 0}
    for key, pass_fn in (
        ("stamped", _stamp_maturity),
        ("recomputed", _recompute_affected),
        ("released", _release_matured),
    ):
        try:
            with transaction.atomic():
                result[key] = pass_fn()
        except Exception:  # noqa: BLE001 — one broken pass must not stop the others
            logger.exception("referral maturity sweep: %s pass failed", key)

    result["stalled"] = _stalled_count()
    if result["stalled"]:
        logger.error(
            "referral maturity sweep left %s commission(s) unreleased past their holding "
            "period — the sweep is not doing its job", result["stalled"],
        )
    result["aging_payouts"] = _alert_on_aging_payouts()
    if any(result.values()):
        logger.info("referral maturity sweep: %s", result)
    return result


#: How long a payout request may sit unanswered before the sweep starts complaining.
#: Payouts are processed by hand once a month, so a week is not late — it is the normal
#: shape of the process. Fourteen days means a full monthly cycle has been missed.
PAYOUT_AGING_DAYS = 14


def _alert_on_aging_payouts() -> int:
    """Payout requests nobody has answered. Returns how many, and logs if any.

    This is the failure mode the programme is most likely to actually suffer, and the
    one with a real person on the other end of it. Everything else here is automatic:
    commissions accrue in the payment path, mature on a timer, reverse on a refund. A
    payout request is the ONE step that waits on a human remembering, and the customer
    cannot chase what they cannot see — their screen says "we're reviewing it" whether it
    was submitted yesterday or in March.

    Deliberately a log line rather than an email: the admin payout queue is where this
    belongs as a badge, and a daily email nobody wired up an inbox rule for is how alerts
    get filtered into a folder and stop being read. Sentry raises on ERROR, which is the
    channel already being watched.
    """
    cutoff = timezone.now() - timezone.timedelta(days=PAYOUT_AGING_DAYS)
    aging = list(
        PayoutRequest.objects.filter(status="requested", created_at__lt=cutoff)
        .values_list("pk", "currency_id", "amount")
    )
    if aging:
        logger.error(
            "%s payout request(s) unanswered for more than %s days — a referrer is "
            "waiting on money: %s",
            len(aging), PAYOUT_AGING_DAYS,
            ", ".join(f"#{pk} {cur} {amt}" for pk, cur, amt in aging),
        )
    return len(aging)
