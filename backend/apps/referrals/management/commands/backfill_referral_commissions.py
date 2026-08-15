"""Write commissions for referred, paid orders that do not have one.

THIS IS THE OTHER HALF OF A DELIBERATE TRADE. `services.accrue_for_order` runs inside
the payment-confirmation transaction and swallows every exception it meets, because an
error there would roll back a payment that has already been charged. That trade is only
honest if the lost work is recoverable — this command is the recovery.

Run it after any Sentry alert reading "referral accrual failed", and after deploying the
feature (to pick up orders placed with a `?ref=` link between the storefront shipping and
the backend shipping, if they ever go out of step).

Idempotent by construction: `Commission.order` is unique and this only creates missing
rows. It never edits an existing commission, so a re-run cannot rewrite history.
"""
from django.core.management.base import BaseCommand

from apps.orders.models import Order
from apps.referrals.models import Commission
from apps.referrals.services import SHIPPED_ONWARDS, accrue_for_order


class Command(BaseCommand):
    help = "Create missing referral commissions for paid orders carrying a referral code."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--order", action="append", default=[],
            help="Limit to specific order numbers (repeatable).",
        )

    def handle(self, *args, **options):
        # Paid means "past pending_payment and not dead". `processing` is included
        # because a commission starts life pending and its holding clock only begins at
        # shipping — an order that is paid but not yet dispatched should still have its
        # row, waiting.
        payable = set(SHIPPED_ONWARDS) | {"processing"}
        orders = (
            Order.objects.exclude(referral_code="")
            .filter(status__in=payable)
            .exclude(pk__in=Commission.objects.values("order_id"))
            .select_related("country", "currency")
            .order_by("pk")
        )
        if options["order"]:
            orders = orders.filter(number__in=options["order"])

        if options["dry_run"]:
            self.stdout.write(f"{orders.count()} order(s) are missing a commission.")
            for order in orders[:20]:
                self.stdout.write(f"  {order.number}  ref={order.referral_code}")
            return

        written = 0
        for order in orders.iterator(chunk_size=200):
            if accrue_for_order(order) is not None:
                written += 1
        self.stdout.write(self.style.SUCCESS(f"Wrote {written} commission(s)."))
