"""The referral programme's data model.

Every registered customer is a referrer — there is no application and no approval step
(Hammed, 2026-08-14). A `ReferralProfile` is therefore not a membership record; it is
just the place a customer's code lives, created lazily the first time they look at the
page and backfilled by `manage.py backfill_referral_codes`.

── THE FOUR TABLES AND WHY EACH ONE EXISTS ──────────────────────────────────────────

`ReferralProfile`  the code, and the two things that can be true ABOUT a referrer
                   (blocked; accepted the terms).
`Commission`       one row per referred ORDER. The money.
`ReferralAdjustment` a SIGNED correction that is not attached to an order's own
                   commission: a clawback after the money already went out, or a
                   manual bonus. See the class docstring — this table is the reason
                   the ledger can survive a refund on day 70.
`PayoutMethod` /   where a referrer's money goes, and each request to send it.
`PayoutRequest`

── WHAT "THE BALANCE" IS, IN ONE PLACE ──────────────────────────────────────────────

There is no stored balance column anywhere, deliberately. A denormalised balance is a
second source of truth about money, and the day it disagrees with the rows is the day
nobody can say which one is right. Balances are always derived, by `services.balances()`:

    available = Σ Commission(status=available).amount + Σ ReferralAdjustment.amount
    pending   = Σ Commission(status=pending).amount
    lifetime  = Σ Commission(status in available|paid).amount + Σ positive adjustments

all grouped by currency, because this programme never converts money between
currencies (see `services` for that ruling).

── MULTI-CURRENCY, STATED ONCE ──────────────────────────────────────────────────────

The published terms name one threshold, ₦20,000, because the WordPress programme only
ever ran in Nigeria. This platform sells in NGN/GBP/USD/CAD, so a referrer can earn in
four currencies. Hammed's ruling (2026-08-14): **per-currency wallets, no FX
conversion, ever.** A stored conversion rate would be an audit surface and a dispute
surface — "why was my £14 worth ₦18,000 in March and ₦21,000 in May" is not a
conversation this shop needs to have. Each currency has its own balance, its own
threshold (`settings.REFERRAL_PAYOUT_THRESHOLDS`) and its own payout requests.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models.functions import Upper

from apps.core.models import TimeStampedModel


class ReferralProfile(TimeStampedModel):
    """A customer's referral identity. Auto-created; never applied for.

    `code` is stored UPPERCASE and is unique case-insensitively, exactly like
    `checkout.Coupon.code` — a referrer will write their code in a caption in whatever
    case they like, and "AMINA7K3" and "amina7k3" must not be two different people.

    `is_blocked` is the whole of the abuse response for v1 and it is deliberately
    coarse: it stops NEW commissions accruing and stops payout requests, and it does
    not touch money already earned. Taking earned money back is `ReferralAdjustment`'s
    job and it should require someone to type a reason.

    `terms_accepted_at` / `terms_version` are recorded at the FIRST PAYOUT REQUEST, not
    at signup. Auto-enrolment means nobody ever clicked anything to join, so there is no
    natural moment to collect agreement — but the moment money is about to move is a
    moment the customer is paying attention, and the clauses that matter in a dispute
    (no self-referral, clawback on returns) are the ones they are about to be paid
    under. One boolean and one datetime; cheap now, and the thing we would wish for
    during the first argument.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referral_profile"
    )
    code = models.CharField(max_length=32)
    is_blocked = models.BooleanField(default=False)
    blocked_reason = models.TextField(blank=True)
    terms_version = models.CharField(max_length=20, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(Upper("code"), name="uniq_referral_code_ci")]

    def __str__(self) -> str:
        return f"{self.code} ({self.user_id})"

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)


class Commission(TimeStampedModel):
    """What one referred order earned. One row per order, forever.

    ── THE LIFECYCLE, AND WHERE EACH MOVE HAPPENS ───────────────────────────────────

        pending ──(matures)──> available ──(payout paid)──> paid
           │                       │
           └──────(refund / cancel)┴──────> reversed

    `pending`   written by `services.accrue_for_order`, from inside `_fulfil_locked` —
                i.e. the instant the money for the order is confirmed, and never before.
    `available` flipped by the nightly `mature_commissions` task, 60 days after the
                order SHIPPED. Not 60 days after payment: the holding period exists to
                cover returns, and a return window runs from delivery, not from the
                card clearing. An order that takes three weeks to reach the customer
                has not had its return window run down by the shipping time — the same
                reasoning `orders.tasks.complete_delivered_orders` is built on.
    `paid`      set when a PayoutRequest is marked paid.
    `reversed`  the order died. Terminal.

    ── THE SNAPSHOTS, AND WHY THEY ARE SNAPSHOTS ────────────────────────────────────

    `rate_percent` is copied in at accrual and never read from settings again. If the
    programme ever moves off 10%, every commission already earned must keep the rate it
    was earned under; a rate read live at display time silently rewrites history.

    `base_amount` is likewise frozen. It is NOT `order.subtotal` and the difference is
    the whole point — see `services.commission_base` for the arithmetic and for why the
    embedded VAT has to come out of it.

    `currency` is the ORDER's currency, not the referrer's anything. There is no
    referrer currency; there are per-currency wallets.

    ── WHY `order` IS A OneToOneField ───────────────────────────────────────────────

    It is the idempotency key. Accrual runs inside the payment-confirmation path, which
    is driven by gateway webhooks that redeliver freely, so `get_or_create` on a unique
    order is what makes a replayed webhook a no-op instead of a second commission.
    """

    STATUS_CHOICES = [
        ("pending", "Pending — holding period"),
        ("available", "Available to withdraw"),
        ("paid", "Paid out"),
        ("reversed", "Reversed"),
    ]

    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referral_commissions"
    )
    order = models.OneToOneField(
        "orders.Order", on_delete=models.CASCADE, related_name="referral_commission"
    )
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)

    base_amount = models.DecimalField(max_digits=12, decimal_places=2)
    rate_percent = models.DecimalField(max_digits=5, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="pending")
    # NULL until the order ships. The nightly sweep stamps it from the order's
    # `status:shipped` event, so the date the customer is shown is the real one rather
    # than a guess made at accrual time about when the parcel might leave.
    matures_at = models.DateTimeField(null=True, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_reason = models.TextField(blank=True)

    # PROTECT, not SET_NULL. A commission's `paid` status means "claimed by that payout",
    # so the FK is not decoration — it is the only thing tying the row to the money. Under
    # SET_NULL, deleting a PayoutRequest (one click in the Django admin) would leave every
    # commission it claimed sitting at `paid` pointing at nothing: invisible to the
    # available balance, invisible to the payout history, and unrecoverable without
    # hand-written SQL. Silent, permanent, and money. PROTECT refuses the delete instead;
    # a payout that should not have existed is cancelled through `reject_payout`, which
    # releases its commissions properly.
    payout = models.ForeignKey(
        "referrals.PayoutRequest", null=True, blank=True,
        on_delete=models.PROTECT, related_name="commissions",
    )

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            # The account page's balance query and the payout picker both filter on
            # exactly this pair.
            models.Index(fields=["referrer", "status"]),
            # The nightly maturity sweep's driving filter.
            models.Index(fields=["status", "matures_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.amount} {self.currency_id} to {self.referrer_id} ({self.status})"

    @property
    def is_settled(self) -> bool:
        """Money has left, or will never leave. Nothing further accrues on this row."""
        return self.status in ("paid", "reversed")


class ReferralAdjustment(TimeStampedModel):
    """A signed correction to a referrer's balance that no Commission row can carry.

    THE CASE THIS EXISTS FOR, because it is not obvious and it WILL happen: a customer
    returns a referred order on day 70. The commission matured on day 60 and was paid
    out on day 65. There is no way to un-pay it — the money is in someone's bank
    account — and rewriting the `paid` Commission would make the payout it belongs to
    stop adding up. So the clawback is recorded here as a NEGATIVE row against the
    referrer's wallet in that currency, and it nets against future earnings.

    The balance is therefore allowed to go negative, and `services.request_payout`
    refuses while it is. That is the correct outcome: the shop does not chase a
    customer for ₦900, it simply does not pay the next ₦900 twice.

    The same table carries manual credits — a ₦200k Club retainer, a goodwill payment,
    a correction after a support call — because they are the same shape (signed money,
    a reason, a person who authorised it) and a second table would only mean two places
    to look when a balance is wrong.

    `reason` is not optional in practice: every writer passes one, because a row here is
    the only explanation a referrer will ever get for money appearing or disappearing.
    """

    KIND_CHOICES = [
        ("clawback", "Clawback — refunded after payout"),
        ("bonus", "Bonus / retainer"),
        ("correction", "Manual correction"),
    ]

    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referral_adjustments"
    )
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    # SIGNED. Negative for a clawback, positive for a bonus. Not two columns and not an
    # unsigned amount plus a direction flag: a sum() that has to consult a flag is a
    # sum() somebody eventually gets backwards.
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    reason = models.TextField()
    order = models.ForeignKey(
        "orders.Order", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="referral_adjustments",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    # NULL while this adjustment still moves the balance; set to the payout that netted
    # it. Exactly the role `Commission.payout` plays, and for the same reason: the
    # available balance is DERIVED, so a settled adjustment has to stop being counted
    # or it would be netted into every future payout as well. Pointing it at the request
    # that consumed it does that without editing the amount, so the referrer's history
    # still shows the original clawback rather than a mysteriously-zeroed row.
    # PROTECT for the same reason as `Commission.payout`, in the opposite direction: a
    # settled adjustment that lost its link would be netted into the NEXT payout as well,
    # charging the referrer the same clawback twice.
    settled_by = models.ForeignKey(
        "referrals.PayoutRequest", null=True, blank=True,
        on_delete=models.PROTECT, related_name="adjustments",
    )

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["referrer", "currency", "settled_by"])]

    def __str__(self) -> str:
        return f"{self.amount} {self.currency_id} to {self.referrer_id} ({self.kind})"


class PayoutMethod(TimeStampedModel):
    """Where one referrer's money goes, in one currency.

    ── WHAT IS AND IS NOT PROTECTED HERE, STATED PLAINLY ────────────────────────────

    The account number is stored in the clear. That is a decision (Hammed, 2026-08-14),
    not an oversight, and the reasoning is that the threat model points the other way: a
    Nigerian NUBAN is semi-public — people publish them in Instagram bios to take
    payment — so confidentiality buys little, while a `PAYOUT_ENCRYPTION_KEY` buys a
    real operational risk (lose it and every referrer's bank details are gone) for that
    little.

    The attack that actually costs money is MODIFICATION: someone takes over an account,
    swaps the payout details, and requests a withdrawal. The controls are aimed there:

    1. The API never returns the full account number — `account_number_masked` is what
       serialisers publish, and the raw column is write-only over HTTP.
    2. Every change emails the account holder (`services.save_payout_method`), so a
       silent swap is not silent.
    3. Every change is audit-logged, and every PayoutRequest snapshots the details it
       was made against, so "where did the money actually go" is answerable later even
       if the method has since been edited.

    What is NOT here, and is the honest next step rather than a claimed control: live
    account-name resolution against Paystack/Flutterwave, which would catch a number
    that does not belong to the name given. It needs a bank-code list and a cached bank
    directory; `bank_code` exists so that work is a service change and not a migration.

    One row per (user, currency): a referrer paid in naira and in sterling needs two
    accounts, and pairing the account with the currency at the point of entry is what
    stops a GBP balance being sent to a naira account.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payout_methods"
    )
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    bank_name = models.CharField(max_length=120)
    account_name = models.CharField(max_length=120)
    account_number = models.CharField(max_length=64)  # or IBAN
    # Empty until live account-name resolution lands; see the class docstring.
    bank_code = models.CharField(max_length=20, blank=True)
    # Per-market shape, same idea as payments.BankAccount.extra: sort_code (GB),
    # routing_number (US), IBAN/SWIFT (intl). Display/handoff data only.
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "currency"], name="uniq_payout_method_ccy"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.currency_id}: {self.bank_name} {self.account_number_masked}"

    @property
    def account_number_masked(self) -> str:
        """The ONLY form of the number that goes over the wire to a browser.

        Last four, or the whole thing if it is short enough that masking would be
        theatre. Never raises on a short value — a four-character account number is not
        real, but a 500 on the account page over one is worse than showing it.
        """
        tail = self.account_number[-4:]
        return f"•••• {tail}" if len(self.account_number) > 4 else self.account_number

    def snapshot(self) -> dict:
        """The immutable record of where a payout was sent, frozen onto the request.

        Full number here, unlike the API shape: this is the shop's own record of a bank
        transfer it made, and a masked audit trail cannot answer "which account did the
        ₦48,500 go to" six months later.
        """
        return {
            "bank_name": self.bank_name,
            "account_name": self.account_name,
            "account_number": self.account_number,
            "bank_code": self.bank_code,
            "currency": self.currency_id,
            "extra": self.extra,
        }


class PayoutRequest(TimeStampedModel):
    """One request to send a referrer their available balance in one currency.

    ── THE AMOUNT IS FROZEN AT REQUEST TIME ─────────────────────────────────────────

    `amount` is the balance as it stood when the customer asked, and the Commission rows
    that made it up are linked (`Commission.payout`) in the same transaction. It is not
    recomputed at approval. If it were, a commission that matured in the gap would be
    swept into a payout the customer never asked for and staff already eyeballed, and a
    reversal in the gap would pay out an amount that no longer exists.

    ── THE STATUSES ─────────────────────────────────────────────────────────────────

        requested ──> approved ──> paid
             └──────> rejected

    `requested` the customer asked. Their commissions are already claimed by this row,
                so they cannot be double-requested.
    `approved`  staff checked the fraud flags and mean to send it. Kept distinct from
                `paid` because the money leaves by hand, at a bank, on the last business
                day of the month — the gap between "we will pay this" and "it left" is
                real and lasts days.
    `paid`      the transfer went. `reference` carries the bank's, which is the only
                thing that settles "I never got it".
    `rejected`  staff refused it. The linked commissions are RELEASED back to
                `available` (see `services.reject_payout`) — a rejected request must not
                strand a referrer's money in limbo forever.

    Deliberately NOT here: automated transfer execution. Payouts are monthly, manual,
    and hand-checked, and that manual review IS the programme's main fraud control for
    v1. Wiring Flutterwave transfers in before the admin review screen exists would
    remove the control and keep the risk.
    """

    STATUS_CHOICES = [
        ("requested", "Requested"),
        ("approved", "Approved"),
        ("paid", "Paid"),
        ("rejected", "Rejected"),
    ]

    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payout_requests"
    )
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="requested")
    # Frozen copy of the PayoutMethod as it was when the request was made. The method
    # itself may be edited or deleted afterwards; this is what the money was sent to.
    method_snapshot = models.JSONField(default=dict)

    # ── WITHHOLDING, SNAPSHOT AT REQUEST TIME ────────────────────────────────────────
    #
    # `amount` above is the GROSS — what the referrer earned, and what the commission
    # rows behind this request add up to. It keeps that meaning; the three fields here
    # are what happens to it on the way out.
    #
    # ZERO TODAY. Hammed's ruling of 2026-08-15 is that commission is paid in full, to
    # residents and non-residents alike. The fields exist anyway, because the alternative
    # is discovering on the day an accountant says otherwise that "how much did we
    # actually send" and "how much did they earn" were the same column all along — and by
    # then there are rows nobody can restate. Recording a zero deduction against a stated
    # rate is also the honest answer to "why was nothing withheld from this payment".
    #
    # The RATE is snapshot, not read live, for the same reason `Commission.rate_percent`
    # is: a rate change must not silently re-cut a request that is already open, and a
    # row should be able to answer what it was paid under without consulting settings
    # that have moved on. See `settings.REFERRAL_WHT_PERCENT`.
    wht_rate_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    wht_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # What actually leaves the bank: gross minus withholding. Stored rather than derived
    # because it is the figure a bank statement is reconciled against, and a derived
    # column that disagrees with a statement is an argument nobody can settle.
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Filled only if a deduction is ever actually remitted to a tax authority. Nullable
    # and empty by design: with the rate at zero there is nothing to remit, and a blank
    # here means "no deduction was taken", not "we forgot".
    wht_remittance_reference = models.CharField(max_length=100, blank=True)
    wht_remitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    reference = models.CharField(max_length=100, blank=True)  # the bank's transfer ref
    admin_note = models.TextField(blank=True)
    # Shown to the customer when a request is refused. Separate from admin_note on
    # purpose: staff must be able to write "same address as three other referrers"
    # somewhere the person it is about cannot read.
    customer_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["referrer", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"payout {self.pk}: {self.amount} {self.currency_id} ({self.status})"

    @property
    def is_open(self) -> bool:
        """Still claiming its commissions. One open request per currency at a time."""
        return self.status in ("requested", "approved")


# Sums over an empty queryset come back as None; every caller wants zero.
ZERO = Decimal("0.00")
