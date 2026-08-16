"""The payout queue, as staff see it.

The customer serializer next door masks the account number. THIS ONE DOES NOT, and that
is the whole difference between the two files: a person cannot make a bank transfer to
`•••• 6789`. The account number leaves the database exactly once, to the one screen whose
job is to type it into a banking app, behind `referrals.view` and with the read audited
(see `PayoutQueueViewSet`).

What is published is the SNAPSHOT taken when the request was made, never the referrer's
current `PayoutMethod`. That is not a convenience — it is the account-takeover control.
A hijacker who changes the bank details while a request is in flight changes what the
customer's own page shows and does not change what staff are told to pay. The mismatch
surfaces as a fraud flag instead (`services.fraud_flags`), where a human can ask about it.
"""
from rest_framework import serializers

from apps.referrals.services import fraud_flags


class PayoutQueueSerializer(serializers.Serializer):
    """One row of the queue. Read-only; every state change goes through a service."""

    id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    status = serializers.CharField()
    currency = serializers.CharField(source="currency.code")
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)

    referrer_name = serializers.SerializerMethodField()
    referrer_email = serializers.CharField(source="referrer.email")
    referrer_toke_id = serializers.CharField(source="referrer.toke_id")
    referrer_id = serializers.IntegerField()
    referrer_is_blocked = serializers.SerializerMethodField()

    # The bank details, unmasked, from the snapshot. See the module docstring.
    bank_name = serializers.SerializerMethodField()
    account_name = serializers.SerializerMethodField()
    account_number = serializers.SerializerMethodField()
    bank_code = serializers.SerializerMethodField()

    commission_count = serializers.SerializerMethodField()
    flags = serializers.SerializerMethodField()
    days_open = serializers.SerializerMethodField()

    decided_at = serializers.DateTimeField()
    decided_by_email = serializers.SerializerMethodField()
    paid_at = serializers.DateTimeField()
    reference = serializers.CharField()
    admin_note = serializers.CharField()
    customer_message = serializers.CharField()

    def get_decided_by_email(self, r) -> str:
        """Who decided it. Blank rather than null while nobody has — the queue renders it
        straight into a cell, and "None" is not a person's name."""
        return r.decided_by.email if r.decided_by_id else ""

    def get_referrer_name(self, r) -> str:
        return f"{r.referrer.first_name} {r.referrer.last_name}".strip() or r.referrer.email

    def get_referrer_is_blocked(self, r) -> bool:
        profile = getattr(r.referrer, "referral_profile", None)
        return bool(profile and profile.is_blocked)

    def _snap(self, r, key: str) -> str:
        return str((r.method_snapshot or {}).get(key, ""))

    def get_bank_name(self, r) -> str:
        return self._snap(r, "bank_name")

    def get_account_name(self, r) -> str:
        return self._snap(r, "account_name")

    def get_account_number(self, r) -> str:
        return self._snap(r, "account_number")

    def get_bank_code(self, r) -> str:
        return self._snap(r, "bank_code")

    def get_commission_count(self, r) -> int:
        return r.commissions.count()

    def get_flags(self, r) -> list[str]:
        """Computed per row rather than stored. A flag is a reading of the data as it is
        NOW — "bank details changed since the request" becomes true after the fact, and a
        stored copy would still say the request was clean."""
        return fraud_flags(r)

    def get_days_open(self, r) -> int | None:
        """How long the customer has been waiting, for requests nobody has answered.

        None once a decision exists, because the number stops meaning anything then. The
        queue sorts on it, and the storefront tells the customer nothing but "we're
        reviewing it", so this is the only place the wait is visible to anyone.
        """
        if r.status != "requested":
            return None
        from django.utils import timezone

        return (timezone.now() - r.created_at).days


class PayoutCommissionSerializer(serializers.Serializer):
    """The orders a payout is made of — shown on the detail screen so a reviewer can see
    WHAT they are paying for, which is where most fraud is visible."""

    id = serializers.IntegerField()
    order_number = serializers.CharField(source="order.number")
    order_status = serializers.CharField(source="order.status")
    base_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    rate_percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    created_at = serializers.DateTimeField()


class RejectPayoutSerializer(serializers.Serializer):
    """`customer_message` is REQUIRED and goes on the customer's payout history.

    A rejection with no reason is the version that generates a support ticket every
    single time, and the reviewer is the only person who knows why. Making it mandatory
    at the serializer costs one field and removes that whole class of ticket.
    """

    customer_message = serializers.CharField(max_length=500, allow_blank=False)
    admin_note = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class ApprovePayoutSerializer(serializers.Serializer):
    admin_note = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class MarkPaidSerializer(serializers.Serializer):
    """`reference` is the bank's transfer reference and the service refuses without it —
    it is the only artefact that answers "I never received it"."""

    reference = serializers.CharField(max_length=100, allow_blank=False)
    admin_note = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class ReferrerSerializer(serializers.Serializer):
    """A referrer as the abuse/adjustment screen sees them.

    Balances are computed per row rather than annotated, which is O(referrers) queries
    and is the right trade at this size: `services.balances()` is the ONLY place that
    knows what a balance is (matured commissions, unsettled adjustments, per currency,
    no FX), and a hand-written annotation here would be a second definition of money
    that drifts from the first. Revisit if this list ever pages past a few hundred.
    """

    id = serializers.IntegerField(source="user.id")
    email = serializers.CharField(source="user.email")
    toke_id = serializers.CharField(source="user.toke_id")
    name = serializers.SerializerMethodField()
    code = serializers.CharField()
    is_blocked = serializers.BooleanField()
    blocked_reason = serializers.CharField()
    joined = serializers.DateTimeField(source="user.date_joined")
    referred_customers = serializers.SerializerMethodField()
    balances = serializers.SerializerMethodField()

    def get_name(self, p) -> str:
        return f"{p.user.first_name} {p.user.last_name}".strip() or p.user.email

    def get_referred_customers(self, p) -> int:
        from apps.referrals.services import referred_customer_count

        return referred_customer_count(p.user)

    def get_balances(self, p) -> list[dict]:
        from apps.referrals.services import balances

        return [
            {
                "currency": w.currency.code,
                "available": str(w.available),
                "pending": str(w.pending),
                "lifetime": str(w.lifetime),
            }
            for w in balances(p.user)
        ]


class BlockReferrerSerializer(serializers.Serializer):
    """`reason` is required to block and ignored to unblock — see
    `services.set_referrer_blocked` for why the two directions differ."""

    blocked = serializers.BooleanField()
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class AdjustmentSerializer(serializers.Serializer):
    """A hand-written correction. `amount` is SIGNED: negative takes money away.

    Deliberately not split into an unsigned amount plus a direction dropdown. The sign is
    the whole meaning of the row, and a UI that hides it behind a select is a UI where
    somebody eventually credits what they meant to claw back.
    """

    currency = serializers.CharField(max_length=3)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    kind = serializers.ChoiceField(choices=["clawback", "bonus", "correction"])
    reason = serializers.CharField(max_length=1000, allow_blank=False)


class AdjustmentRowSerializer(serializers.Serializer):
    """An adjustment already written, for the history list under the form."""

    id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    currency = serializers.CharField(source="currency.code")
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    kind = serializers.CharField()
    reason = serializers.CharField()
    created_by_email = serializers.SerializerMethodField()
    settled = serializers.SerializerMethodField()

    def get_created_by_email(self, a) -> str:
        return a.created_by.email if a.created_by_id else "system"

    def get_settled(self, a) -> bool:
        """Whether a payout has already absorbed it. A settled adjustment is history; an
        unsettled one is still moving the referrer's available balance right now."""
        return a.settled_by_id is not None
