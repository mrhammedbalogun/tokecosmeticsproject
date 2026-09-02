"""Seed migration-SHAPED order history for verifying the reports (Plan-20a).

── WHY MIGRATION-SHAPED, NOT JUST "SOME ORDERS" ────────────────────────────────────

Plan-20's verification ruling: seeded data with known expected values is a better
correctness check than one real order — but only if it has the shape Plan-23 will
actually produce. Clean single-currency rows with tidy variant links would let every
report pass here and fail the day 879 legacy orders land. So this seeds:

  * two currencies (the no-FX-mixing rule is unexercisable on NGN-only data),
  * order items with `variant=NULL` (the unattributed bucket),
  * `legacy_number` set, and historical `completed` / `refunded` statuses,
  * a refund, so gross/refunds/net have something to reconcile.

── IT REFUSES TO RUN AGAINST A REAL DATABASE ───────────────────────────────────────

This project's database is live. The command aborts if the orders table already holds
anything that did not come from it, so the worst case is a no-op rather than fabricated
revenue mixed into real history.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.models import Country, Currency
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment, Refund

PREFIX = "SEED-"


def _purge_seeded():
    """Delete the seeded rows in FK-safe order.

    `Payment.order` and `Refund.payment` are both PROTECT, so deleting the orders
    first raises ProtectedError as soon as one seeded refund exists — which made this
    command un-re-runnable after its own first successful run.
    """
    orders = Order.objects.filter(number__startswith=PREFIX)
    Refund.objects.filter(payment__order__in=orders).delete()
    Payment.objects.filter(order__in=orders).delete()
    return orders.delete()


class Command(BaseCommand):
    help = "Seed migration-shaped orders for report verification. Refuses on real data."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Remove seeded rows and stop.")

    def handle(self, *args, **options):
        if options["clear"]:
            deleted, _ = _purge_seeded()
            self.stdout.write(self.style.SUCCESS(f"Removed {deleted} seeded rows."))
            return

        real = Order.objects.exclude(number__startswith=PREFIX).count()
        if real:
            raise CommandError(
                f"{real} order(s) here did not come from this command. Refusing to seed "
                "into real history — run against an empty or already-seeded database."
            )

        _purge_seeded()
        now = timezone.now()
        ng, gb = Country.objects.get(code="NG"), Country.objects.get(code="GB")
        ngn, gbp = Currency.objects.get(code="NGN"), Currency.objects.get(code="GBP")

        made = 0
        for day in range(30):
            placed = now - timedelta(days=day)
            # NGN, attributed to nothing — the migrated shape.
            order = Order.objects.create(
                number=f"{PREFIX}NG-{day}", legacy_number=f"WP-{1000 + day}",
                email=f"buyer{day % 7}@example.com", country=ng, currency=ngn,
                status="completed" if day % 5 else "refunded",
                grand_total=Decimal("20000") + Decimal(day) * 100,
                discount_total=Decimal("500") if day % 4 == 0 else Decimal("0"),
                placed_at=placed,
            )
            OrderItem.objects.create(
                order=order, variant=None, product_name="Radiance Glow Serum",
                sku="TOKE-RADIANCEGLOWSERU-30ML", unit_price=order.grand_total,
                line_total=order.grand_total, quantity=1,
            )
            made += 1

            if day % 5 == 0:
                # A second currency, so the side-by-side rule is exercised.
                gb_order = Order.objects.create(
                    number=f"{PREFIX}GB-{day}", legacy_number=f"WPUK-{2000 + day}",
                    email=f"uk{day % 3}@example.com", country=gb, currency=gbp,
                    status="completed", grand_total=Decimal("45") + day,
                    placed_at=placed,
                )
                OrderItem.objects.create(
                    order=gb_order, variant=None, product_name="Shea Whip Body Butter",
                    sku="TOKE-SHEAWHIP-200G", unit_price=gb_order.grand_total,
                    line_total=gb_order.grand_total, quantity=1,
                )
                made += 1

            if order.status == "refunded":
                payment = Payment.objects.create(
                    order=order, gateway="bank_transfer", purpose="goods",
                    status="succeeded", amount=order.grand_total, currency=ngn,
                    # `idempotency_key` is unique with no default, so leaving it unset
                    # gave every payment "" and collided on the SECOND refunded order.
                    idempotency_key=f"{PREFIX}pay-{order.number}",
                )
                Refund.objects.create(
                    payment=payment, amount=order.grand_total / 2, status="succeeded",
                    reason="seeded",
                )

        self.stdout.write(self.style.SUCCESS(f"Seeded {made} migration-shaped orders."))
