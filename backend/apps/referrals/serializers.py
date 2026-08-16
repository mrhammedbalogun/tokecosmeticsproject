"""API shapes for the customer's own referral page.

Money is published TWICE everywhere: the raw Decimal (for arithmetic and progress bars)
and a `*_display` string built by `format_money` (for showing a human). That is the same
contract `orders.serializers` uses, and the reason is the one stated in
`payments.money.format_money`: a currency's precision has exactly one source of truth,
and a React component formatting `48500` with a hardcoded `₦` and two decimals will get
a zero-decimal currency 100× wrong the day the shop adds one.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.payments.money import format_money


class WalletSerializer(serializers.Serializer):
    """One currency's balance. Built from `services.Wallet`, which is a dataclass, so
    every field here is read off attributes rather than a model."""

    currency = serializers.CharField(source="currency.code")
    symbol = serializers.CharField(source="currency.symbol")

    available = serializers.DecimalField(max_digits=12, decimal_places=2)
    pending = serializers.DecimalField(max_digits=12, decimal_places=2)
    paid = serializers.DecimalField(max_digits=12, decimal_places=2)
    lifetime = serializers.DecimalField(max_digits=12, decimal_places=2)
    threshold = serializers.DecimalField(max_digits=12, decimal_places=2)

    available_display = serializers.SerializerMethodField()
    pending_display = serializers.SerializerMethodField()
    paid_display = serializers.SerializerMethodField()
    lifetime_display = serializers.SerializerMethodField()
    threshold_display = serializers.SerializerMethodField()

    can_request = serializers.BooleanField()
    # How much more is needed before the withdraw button turns on. Computed server-side
    # rather than left to the client to subtract, so the "₦11,500 to go" line and the
    # rule that actually gates the button can never disagree.
    remaining_to_threshold = serializers.SerializerMethodField()
    remaining_to_threshold_display = serializers.SerializerMethodField()
    open_request_id = serializers.SerializerMethodField()

    def get_available_display(self, w) -> str:
        return format_money(w.available, w.currency)

    def get_pending_display(self, w) -> str:
        return format_money(w.pending, w.currency)

    def get_paid_display(self, w) -> str:
        return format_money(w.paid, w.currency)

    def get_lifetime_display(self, w) -> str:
        return format_money(w.lifetime, w.currency)

    def get_threshold_display(self, w) -> str:
        return format_money(w.threshold, w.currency)

    def get_remaining_to_threshold(self, w):
        return max(w.threshold - w.available, 0)

    def get_remaining_to_threshold_display(self, w) -> str:
        return format_money(max(w.threshold - w.available, 0), w.currency)

    def get_open_request_id(self, w):
        return w.open_request.pk if w.open_request else None


class TierSerializer(serializers.Serializer):
    """₦200k Club progress. `qualifying_sales` is net SALES driven, not commission — see
    `services.tier_progress` for why those are different numbers."""

    currency = serializers.CharField(source="currency.code")
    qualifying_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    threshold = serializers.DecimalField(max_digits=12, decimal_places=2)
    window_days = serializers.IntegerField()
    is_elite = serializers.BooleanField()
    progress_percent = serializers.IntegerField()
    qualifying_sales_display = serializers.SerializerMethodField()
    threshold_display = serializers.SerializerMethodField()
    club_name = serializers.SerializerMethodField()

    def get_qualifying_sales_display(self, t) -> str:
        return format_money(t.qualifying_sales, t.currency)

    def get_threshold_display(self, t) -> str:
        return format_money(t.threshold, t.currency)

    def get_club_name(self, t) -> str:
        """The tier's NAME, which is not the same thing as its threshold formatted.

        The shop published this as "The ₦200k Club" and that is what customers have
        already seen. `format_money` correctly renders the threshold as "₦200,000.00" —
        correct for money, wrong for a name, and "The ₦200,000.00 Club" reads like a
        spreadsheet cell wandered into the marketing.

        Built here rather than hardcoded in the storefront so the name still follows
        `REFERRAL_ELITE_THRESHOLDS` if the number ever moves. Falls back to the full
        formatted amount for any threshold that is not a clean multiple of a thousand,
        because "₦199.5k" is worse than the honest number.
        """
        whole = int(t.threshold)
        if t.threshold == whole and whole >= 1000 and whole % 1000 == 0:
            return f"The {t.currency.symbol}{whole // 1000:,}k Club"
        return f"The {format_money(t.threshold, t.currency)} Club"


class CommissionSerializer(serializers.Serializer):
    """One row of the referrer's activity feed.

    The buyer is described, never identified: `customer_label` is a first name and an
    initial ("Amina O."), because a referrer is entitled to know their link worked and
    is not entitled to a customer's email address. `order_number` is included because it
    is what support will ask for when something is queried, and it identifies an order
    rather than a person.
    """

    id = serializers.IntegerField()
    order_number = serializers.CharField(source="order.number")
    placed_at = serializers.DateTimeField(source="order.placed_at")
    status = serializers.CharField()
    status_label = serializers.SerializerMethodField()
    currency = serializers.CharField(source="currency.code")
    base_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    rate_percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    amount_display = serializers.SerializerMethodField()
    base_amount_display = serializers.SerializerMethodField()
    matures_at = serializers.DateTimeField()
    reversed_reason = serializers.CharField()
    customer_label = serializers.SerializerMethodField()

    def get_amount_display(self, c) -> str:
        return format_money(c.amount, c.currency)

    def get_base_amount_display(self, c) -> str:
        return format_money(c.base_amount, c.currency)

    def get_status_label(self, c) -> str:
        """Plain English for the one column customers read most.

        `pending` is the one that needs explaining and the one the raw word explains
        worst — a referrer seeing "pending" next to an order that was delivered weeks
        ago assumes something is stuck. The label says what is actually happening.

        `paid` NEEDS THE PAYOUT TO ANSWER, and rendering it as "Paid out" flatly was a
        lie waiting for the first withdrawal. The status means "claimed by a payout", not
        "the money reached your bank" — a commission flips to it the moment a request is
        made, while the transfer only leaves on the last working day of the month. A
        referrer reading "Paid out" next to money that has not arrived opens a support
        ticket, and they would be right to.
        """
        if c.status == "paid":
            payout = c.payout
            if payout is None:
                # Only reachable if a payout row was force-deleted, which the FK now
                # refuses (Commission.payout is PROTECT). Honest rather than confident.
                return "Claimed by a payout"
            return {
                "requested": "In a payout being reviewed",
                "approved": "In a payout being sent",
                "paid": "Paid out",
                "rejected": "Payout declined",
            }.get(payout.status, "In a payout")
        return {
            "pending": "In holding period",
            "available": "Ready to withdraw",
            "reversed": "Reversed",
        }.get(c.status, c.status)

    def get_customer_label(self, c) -> str:
        buyer = c.order.user
        if buyer is None:
            return "A customer"
        first = (buyer.first_name or "").strip()
        last = (buyer.last_name or "").strip()
        if not first:
            return "A customer"
        return f"{first} {last[0]}." if last else first


class AdjustmentSerializer(serializers.Serializer):
    """Signed balance corrections, shown in the activity feed alongside commissions —
    a referrer whose balance dropped is owed the row that explains it."""

    id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    kind = serializers.CharField()
    reason = serializers.CharField()
    currency = serializers.CharField(source="currency.code")
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    amount_display = serializers.SerializerMethodField()
    settled = serializers.SerializerMethodField()

    def get_amount_display(self, a) -> str:
        return format_money(a.amount, a.currency)

    def get_settled(self, a) -> bool:
        return a.settled_by_id is not None


class PayoutMethodSerializer(serializers.Serializer):
    """READ shape. The full account number is never in it — see `PayoutMethod`'s
    docstring for the threat model that decision comes from."""

    currency = serializers.CharField(source="currency.code")
    bank_name = serializers.CharField()
    account_name = serializers.CharField()
    account_number_masked = serializers.CharField()
    bank_code = serializers.CharField()
    updated_at = serializers.DateTimeField()


class PayoutMethodWriteSerializer(serializers.Serializer):
    """WRITE shape. Separate class rather than write-only fields on the read one,
    because the two genuinely differ: this accepts a full account number and returns
    nothing, and conflating them is how a masked field ends up round-tripping into
    storage as literal bullets."""

    currency = serializers.CharField(max_length=3)
    bank_name = serializers.CharField(max_length=120)
    account_name = serializers.CharField(max_length=120)
    account_number = serializers.CharField(max_length=64)
    bank_code = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    extra = serializers.DictField(required=False, default=dict)

    def validate_account_number(self, value: str) -> str:
        cleaned = value.replace(" ", "").replace("-", "")
        if not cleaned:
            raise serializers.ValidationError("Enter your account number.")
        # Deliberately loose: NUBAN is 10 digits, but this field also holds IBANs and
        # sort-code/account pairs for the GB/US/CA wallets. Per-market validation
        # belongs with the bank-directory work that `bank_code` is reserved for; a
        # tight rule invented here would reject a legitimate international account.
        if len(cleaned) < 5:
            raise serializers.ValidationError("That account number looks too short.")
        return cleaned


class PayoutRequestSerializer(serializers.Serializer):
    """A payout, as the customer sees it.

    `method_snapshot` is NOT published — it holds the full account number, deliberately
    (it is the shop's audit record of where money went), and the customer already knows
    their own bank. Only the bank name and a masked tail go out, which is enough for
    "which account was this one sent to" without putting the number in an API response.
    """

    id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    currency = serializers.CharField(source="currency.code")
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    amount_display = serializers.SerializerMethodField()
    # What the bank will actually send. Equal to `amount` while withholding is zero (it
    # is, by ruling) — published anyway so the storefront reads the field that stays
    # correct if that ever changes, rather than the one that would quietly overstate.
    net_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    net_amount_display = serializers.SerializerMethodField()
    status = serializers.CharField()
    status_label = serializers.SerializerMethodField()
    paid_at = serializers.DateTimeField()
    reference = serializers.CharField()
    customer_message = serializers.CharField()
    bank_name = serializers.SerializerMethodField()
    account_masked = serializers.SerializerMethodField()

    def get_amount_display(self, r) -> str:
        return format_money(r.amount, r.currency)

    def get_net_amount_display(self, r) -> str:
        return format_money(r.net_amount, r.currency)

    def get_status_label(self, r) -> str:
        return {
            "requested": "Being reviewed",
            "approved": "Approved — sending",
            "paid": "Paid",
            "rejected": "Not approved",
        }.get(r.status, r.status)

    def get_bank_name(self, r) -> str:
        return (r.method_snapshot or {}).get("bank_name", "")

    def get_account_masked(self, r) -> str:
        number = str((r.method_snapshot or {}).get("account_number", ""))
        return f"•••• {number[-4:]}" if len(number) > 4 else number


class PayoutCreateSerializer(serializers.Serializer):
    currency = serializers.CharField(max_length=3)
    # Only ever true on a referrer's FIRST payout; the service ignores it afterwards.
    accept_terms = serializers.BooleanField(default=False)
