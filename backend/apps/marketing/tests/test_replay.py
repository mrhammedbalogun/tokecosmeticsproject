"""`replay_conversions` — the backfill, and the three ways it refuses.

The command exists because the obvious replay is unsafe: `deliver_conversion_event`
re-checks only whether the channel is enabled, so flipping rows to `pending` in a shell
would send every row that was skipped for want of consent. These tests pin the refusals,
not the happy path.
"""
from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.marketing.models import ConversionEvent
from apps.marketing.tests.factories import (
    attribution, channel as make_channel, enable_tracking, make_order,
)

pytestmark = pytest.mark.django_db


def google(**kwargs):
    kwargs.setdefault("pixel_id", "")
    kwargs.setdefault("server_account_id", "3352855298")
    kwargs.setdefault("server_destination_id", "7577766208")
    return make_channel("google_ads", **kwargs)


def skipped(order, reason="no_pixel_id"):
    return ConversionEvent.objects.create(
        channel="google_ads", event_name="purchase", event_id=order.number,
        order=order, status="skipped", last_error=reason,
    )


@pytest.fixture(autouse=True)
def dispatched(monkeypatch):
    """Capture the Celery dispatch instead of performing it.

    `CELERY_TASK_ALWAYS_EAGER` is on in tests, so a real `.delay()` here would run the
    delivery inline, fail on the absent credential, and leave every replayed row
    `failed` — which is a fact about the adapter, not about this command. What the
    command owes is: the right rows flipped to `pending`, and each one handed to the
    queue exactly once.
    """
    from apps.marketing import tasks

    calls: list[int] = []
    monkeypatch.setattr(tasks.deliver_conversion_event, "delay", calls.append)
    return calls


@pytest.fixture
def configured(settings):
    settings.GOOGLE_ADS_DM_CREDENTIALS_B64 = "x"
    enable_tracking()
    return google()


def run(**opts):
    out = StringIO()
    call_command("replay_conversions", stdout=out, **opts)
    return out.getvalue()


def test_a_row_whose_reason_no_longer_applies_is_sent(configured, dispatched):
    order = make_order(user=None, email="a@b.com", status="processing")
    attribution(order, marketing=True)
    event = skipped(order)

    output = run(apply=True)

    event.refresh_from_db()
    assert event.status == "pending"
    assert dispatched == [event.pk], "queued exactly once"
    assert "Queued 1 event" in output


def test_dry_run_is_the_default_and_writes_nothing(configured):
    order = make_order(user=None, email="a@b.com", status="processing")
    attribution(order, marketing=True)
    event = skipped(order)

    output = run()

    event.refresh_from_db()
    assert event.status == "skipped", "a dry run must not touch the outbox"
    assert "DRY RUN" in output


def test_a_non_consenting_row_is_never_replayed(configured, dispatched):
    """THE reason this command exists. `deliver_conversion_event` would have sent it."""
    order = make_order(user=None, email="a@b.com", status="processing")
    attribution(order, marketing=False)
    event = skipped(order, "no_marketing_consent")

    output = run(apply=True)

    event.refresh_from_db()
    assert event.status == "skipped"
    assert dispatched == [], "a non-consenting row must never reach the queue"
    assert "no_marketing_consent" in output
    assert "Queued 0 event" in output


@pytest.mark.parametrize("status", ["cancelled", "expired", "refunded", "pending_payment"])
def test_a_sale_that_was_undone_is_not_reported(configured, status):
    """`_skip_reason` cannot catch this: it is written for the moment an order is paid,
    when these states are unreachable. Weeks later they are not, and reporting a refund
    as a conversion teaches the bidding algorithm to find more refunders."""
    order = make_order(user=None, email="a@b.com", status=status)
    attribution(order, marketing=True)
    event = skipped(order)

    output = run(apply=True)

    event.refresh_from_db()
    assert event.status == "skipped"
    assert f"order_{status}" in output


def test_a_partial_refund_is_still_reported(configured):
    """Deliberately NOT refused: the goods still ship, the sale happened, and the right
    instrument for a changed value is a conversion adjustment."""
    order = make_order(user=None, email="a@b.com", status="shipped")
    attribution(order, marketing=True)
    event = skipped(order)

    run(apply=True)

    event.refresh_from_db()
    assert event.status == "pending"


def test_an_order_past_the_upload_window_is_left_alone(configured):
    order = make_order(user=None, email="a@b.com", status="processing")
    order.placed_at = timezone.now() - timedelta(days=120)
    order.save(update_fields=["placed_at"])
    attribution(order, marketing=True)
    event = skipped(order)

    output = run(apply=True)

    event.refresh_from_db()
    assert event.status == "skipped"
    assert "outside_upload_window" in output


def test_the_window_is_adjustable_for_a_platform_with_a_shorter_one(configured):
    order = make_order(user=None, email="a@b.com", status="processing")
    order.placed_at = timezone.now() - timedelta(days=30)
    order.save(update_fields=["placed_at"])
    attribution(order, marketing=True)
    event = skipped(order)

    run(apply=True, max_age_days=7)

    event.refresh_from_db()
    assert event.status == "skipped"


def test_limit_takes_the_oldest_first(configured):
    """A first run should be small, and the oldest rows are the ones closest to falling
    out of the upload window."""
    events = []
    for days in (10, 5, 1):
        order = make_order(user=None, email=f"a{days}@b.com", status="processing")
        order.placed_at = timezone.now() - timedelta(days=days)
        order.save(update_fields=["placed_at"])
        attribution(order, marketing=True)
        events.append((days, skipped(order)))

    run(apply=True, limit=1)

    by_age = {days: e for days, e in events}
    for event in by_age.values():
        event.refresh_from_db()
    assert by_age[10].status == "pending", "the oldest should go first"
    assert by_age[5].status == "skipped"
    assert by_age[1].status == "skipped"


def test_an_already_sent_row_is_not_reconsidered(configured):
    order = make_order(user=None, email="a@b.com", status="processing")
    attribution(order, marketing=True)
    event = skipped(order)
    event.status = "sent"
    event.save(update_fields=["status"])

    run(apply=True)

    event.refresh_from_db()
    assert event.status == "sent"


def test_an_unknown_channel_is_refused_rather_than_silently_matching_nothing(configured):
    with pytest.raises(CommandError, match="Unknown channel"):
        run(channel="instagram")


def test_a_channel_that_is_still_misconfigured_replays_nothing(settings):
    """The credential is gone, so every row is still ineligible — and the command must
    say so rather than reporting a clean run over zero rows."""
    settings.GOOGLE_ADS_DM_CREDENTIALS_B64 = ""
    enable_tracking()
    google()
    order = make_order(user=None, email="a@b.com", status="processing")
    attribution(order, marketing=True)
    event = skipped(order)

    output = run(apply=True)

    event.refresh_from_db()
    assert event.status == "skipped"
    assert "missing_credential" in output
