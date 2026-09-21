"""Re-send outbox rows that were skipped for a reason that has since been fixed.

DRY-RUN BY DEFAULT. Prints what it would send and writes nothing until --apply.

    python manage.py replay_conversions                    # report only
    python manage.py replay_conversions --apply            # send

── WHY THIS IS A COMMAND AND NOT A LOOP IN A SHELL ────────────────────────────────────

Because the obvious loop is unsafe, in a way that is invisible until it has already
happened. `tasks.deliver_conversion_event` re-checks exactly one thing before it sends —
whether the channel is still enabled. It does NOT re-run `_skip_reason`. So flipping a
batch of `skipped` rows to `pending` and dispatching them would send every row that was
skipped for want of consent, to an ad platform, with the customer's hashed email and
phone attached. The outbox exists to make that impossible, and a replay that bypasses it
is worse than no replay.

Every row is therefore re-judged HERE, against the CURRENT configuration, by the same
`_skip_reason` the live path uses. A row that is still ineligible is left alone and
counted in the report.

── THE THREE GUARDS `_skip_reason` DOES NOT PROVIDE ───────────────────────────────────

`_skip_reason` answers "may we send this", which is not the same as "should we, now".

  1. ORDER OUTCOME. `_skip_reason` is written for the moment an order is paid, when
     `cancelled`/`expired`/`refunded` cannot be its state. A backfill runs weeks later,
     when they can be — and reporting a refunded sale as a conversion teaches the
     bidding algorithm to go and find more customers who will refund. Those statuses are
     refused here.

     A PARTIAL refund is deliberately NOT refused: the order status stays `processing`
     or `shipped` because the goods still ship (see orders/state.py), the sale did
     happen, and the right instrument for a changed value is Google's conversion
     adjustment, not withholding the conversion.

  2. THE UPLOAD WINDOW. Google drops an offline conversion uploaded more than 90 days
     after the associated LAST CLICK, silently — it is not an error, the conversion
     simply never appears. We do not know the click time, only `placed_at`, which is at
     or after it. So this guard is NECESSARY BUT NOT SUFFICIENT: inside the window here
     may still be outside it at Google, and no local check can tell.

  3. THE PII PURGE. `tasks.purge_attribution_pii` blanks `client_ip` and
     `client_user_agent` after 90 days. A row replayed after that still sends, but with
     two fewer match signals, so a backfill is worth less the longer it waits.

── WHAT IT CANNOT DOUBLE-SEND ─────────────────────────────────────────────────────────

Three separate things have to fail before a purchase is counted twice. The task refuses
a row already marked `sent`; the unique constraint on (channel, event_name, event_id)
means no second row can exist for the same order; and every platform dedupes on the id
we send, which for a purchase is the order number.
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

# Reporting a sale that was undone. `expired` and `cancelled` mean no money was ever
# captured; `refunded` means it was given back. See orders/state.py.
UNDONE_STATUSES = frozenset({"cancelled", "expired", "refunded", "pending_payment"})

DEFAULT_MAX_AGE_DAYS = 90


class Command(BaseCommand):
    help = "Re-send conversion outbox rows whose skip reason no longer applies."

    def add_arguments(self, parser):
        parser.add_argument(
            "--channel", default="google_ads",
            help="Channel code to replay (default: google_ads). Only one at a time — "
                 "the windows and the credentials differ per platform.",
        )
        parser.add_argument(
            "--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS,
            help=f"Refuse orders placed longer ago than this (default: {DEFAULT_MAX_AGE_DAYS}, "
                 "Google's offline-conversion limit). See the module docstring for why "
                 "passing this check is not a guarantee.",
        )
        parser.add_argument("--limit", type=int, default=0,
                            help="Send at most this many (0 = no limit). Use it for a first run.")
        parser.add_argument("--apply", action="store_true",
                            help="Actually send. Without it nothing is written.")

    def handle(self, *args, **options):
        from apps.marketing.events import _skip_reason
        from apps.marketing.models import CHANNEL_CODES, ConversionEvent, MarketingChannel
        from apps.marketing.tasks import deliver_conversion_event

        code = options["channel"]
        if code not in CHANNEL_CODES:
            raise CommandError(f"Unknown channel {code!r}. One of: {sorted(CHANNEL_CODES)}")

        row = MarketingChannel.objects.filter(code=code).first()
        if row is None:
            raise CommandError(f"No {code} channel row — nothing is configured to send to.")

        cutoff = timezone.now() - timedelta(days=options["max_age_days"])
        apply = options["apply"]
        limit = options["limit"]

        queryset = (
            ConversionEvent.objects
            .filter(channel=code, status="skipped")
            .select_related("order", "order__marketing_attribution")
            .order_by("order__placed_at")
        )

        eligible, refused = [], {}
        for event in queryset:
            order = event.order
            if order is None:
                refused["order_deleted"] = refused.get("order_deleted", 0) + 1
                continue
            reason = _skip_reason(order, getattr(order, "marketing_attribution", None), row)
            if reason:
                refused[reason] = refused.get(reason, 0) + 1
                continue
            if order.status in UNDONE_STATUSES:
                key = f"order_{order.status}"
                refused[key] = refused.get(key, 0) + 1
                continue
            if order.placed_at < cutoff:
                refused["outside_upload_window"] = refused.get("outside_upload_window", 0) + 1
                continue
            eligible.append(event)

        if limit and len(eligible) > limit:
            self.stdout.write(f"Limiting to the {limit} oldest of {len(eligible)} eligible.")
            eligible = eligible[:limit]

        self.stdout.write(f"\n{code}: {queryset.count()} skipped rows")
        self.stdout.write(f"  eligible to send : {len(eligible)}")
        for reason, count in sorted(refused.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f"  left alone       : {count:4d}  {reason}")

        if eligible:
            oldest, newest = eligible[0].order, eligible[-1].order
            self.stdout.write(
                f"  span             : {oldest.number} ({oldest.placed_at:%Y-%m-%d}) "
                f"-> {newest.number} ({newest.placed_at:%Y-%m-%d})"
            )

        if not apply:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — nothing written. Re-run with --apply to send."))
            return

        sent = 0
        for event in eligible:
            # Flipped to `pending` FIRST, and saved, so a row is never dispatched while
            # still reading `skipped`: the worker would otherwise race this loop and two
            # runs of this command could both queue the same row. The task's own
            # already-sent check is the backstop, not the plan.
            event.status = "pending"
            event.last_error = ""
            event.save(update_fields=["status", "last_error", "updated_at"])
            deliver_conversion_event.delay(event.pk)
            sent += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nQueued {sent} event(s) for delivery. Watch the outbox: a row that Google "
            f"refuses lands as `failed` with its own words in `last_error`."))
