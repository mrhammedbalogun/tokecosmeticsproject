"""The storefront is told the moment the tracking configuration changes.

Pinned because the failure is silent in the direction that matters most. An Owner who
turns `tracking_enabled` off has decided a pixel must stop firing NOW — that is the whole
reason the switch is a checkbox and not a deploy — and without this the storefront would
go on serving the old answer for the length of a TTL, with the admin screen showing
"off" the entire time.

Every test mocks the transport, so nothing here can reach Vercel.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.db.models.signals import post_save
from django.test import override_settings

from apps.cms import revalidate as cms_revalidate
from apps.marketing import revalidate as marketing_revalidate
from apps.marketing.admin_views import ensure_channel_rows
from apps.marketing.models import (
    ConversionEvent,
    MarketingChannel,
    MarketingSettings,
    OrderAttribution,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def notify():
    """`apps.marketing.revalidate` imported `notify_storefront` BY VALUE, so this is the
    name the receivers actually call."""
    with mock.patch.object(marketing_revalidate, "notify_storefront") as m:
        yield m


# ── the two models that are in the cached payload ───────────────────────────────────

def test_changing_the_settings_flushes_the_marketing_tag(notify):
    row = MarketingSettings.load()
    notify.reset_mock()

    row.tracking_enabled = False
    row.save()

    notify.assert_called_once_with(["marketing"])


def test_changing_the_consent_policy_flushes_too(notify):
    """`consent_required_countries` is a legal position, not a preference. Widening it and
    then not asking for five minutes is the failure this prevents."""
    row = MarketingSettings.load()
    notify.reset_mock()

    row.consent_required_countries = ["GB", "IE", "NG"]
    row.save(update_fields=["consent_required_countries"])

    notify.assert_called_once_with(["marketing"])


def test_materialising_the_singleton_flushes_NOTHING(notify):
    """`load()` is a `get_or_create(pk=1)` called by the PUBLIC config view on every
    request. Firing on create would mean the first storefront read of a fresh database
    POSTs straight back at the storefront that asked."""
    MarketingSettings.objects.all().delete()
    notify.reset_mock()

    created = MarketingSettings.load()

    assert created.pk == 1
    assert notify.call_count == 0


def test_editing_a_channel_flushes_the_marketing_tag(notify):
    row = MarketingChannel.objects.create(code="meta", pixel_id="PIXEL123")
    notify.reset_mock()

    row.pixel_id = "PIXEL456"
    row.save(update_fields=["pixel_id", "updated_at"])

    notify.assert_called_once_with(["marketing"])


def test_creating_a_channel_flushes_too(notify):
    """No `created` skip on channels, unlike the settings singleton: a row CAN be born
    meaningful — somebody adding one in the Django admin with a pixel id already in it —
    and skipping that would leave the browser loading nothing for a TTL."""
    MarketingChannel.objects.create(code="tiktok", pixel_id="TT123", is_enabled=True)

    notify.assert_called_once_with(["marketing"])


def test_deleting_a_channel_flushes_the_marketing_tag(notify):
    row = MarketingChannel.objects.create(code="snapchat", pixel_id="SC123")
    notify.reset_mock()

    row.delete()

    notify.assert_called_once_with(["marketing"])


# ── what must NOT flush ─────────────────────────────────────────────────────────────

def test_seeding_the_placeholder_channel_rows_flushes_NOTHING(notify):
    """`ensure_channel_rows()` runs on every GET of the admin screen. It uses
    `bulk_create`, which sends no signals — and the rows it makes carry no pixel id, so
    the public serialiser excludes them anyway. Reading a screen must not purge a cache."""
    MarketingChannel.objects.all().delete()
    notify.reset_mock()

    ensure_channel_rows()

    assert MarketingChannel.objects.exists(), "the seeding must actually have happened"
    assert notify.call_count == 0


@pytest.mark.parametrize("model", [ConversionEvent, OrderAttribution])
def test_the_outbox_and_the_attribution_snapshot_are_not_wired(model, notify):
    """Neither appears in `PublicMarketingConfigSerializer`, so neither is in the cached
    payload — and `ConversionEvent` is written on every order, which would mean flushing
    the tracking config once per sale to publish a value that had not changed.

    Sending the signal directly rather than building an Order: what is under test is the
    dispatch table, and this asks it the exact question a real write would.
    """
    post_save.send(sender=model, instance=model(), created=True)

    assert notify.call_count == 0


# ── failure handling ────────────────────────────────────────────────────────────────

@override_settings(REVALIDATE_SECRET="s3cret", STOREFRONT_BASE_URL="http://shop.test/")
def test_a_dead_storefront_never_costs_the_setting():
    """The business operation is the Owner's decision. Cache invalidation is a side
    effect, and the side effect must not be able to undo it or surface as a 500.

    End to end and SYNCHRONOUSLY: the thread is replaced by one that runs its target
    inline, so the real `_post` really executes against an `httpx` that really raises. A
    backgrounded failure would pass this test by never being looked at; this one makes
    the failure happen inside the save's own call stack, which is the strictest place it
    could possibly go wrong.
    """
    import httpx

    class Inline:
        """threading.Thread's constructor signature, minus the thread."""

        def __init__(self, target=None, args=(), daemon=None):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    row = MarketingSettings.load()

    with mock.patch.object(cms_revalidate.threading, "Thread", Inline), \
            mock.patch.object(cms_revalidate.httpx, "post",
                              side_effect=httpx.ConnectError("down")):
        row.tracking_enabled = False
        row.save()  # must not raise

    row.refresh_from_db()
    assert row.tracking_enabled is False


@override_settings(REVALIDATE_SECRET="s3cret", STOREFRONT_BASE_URL="http://shop.test/")
def test_a_storefront_4xx_never_costs_the_setting_either():
    """The other failure shape: the storefront answers, and refuses. A wrong or missing
    `REVALIDATE_SECRET` on Vercel looks exactly like this, and it must degrade to the TTL
    rather than break the admin screen."""

    class Inline:
        def __init__(self, target=None, args=(), daemon=None):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    row = MarketingSettings.load()

    with mock.patch.object(cms_revalidate.threading, "Thread", Inline), \
            mock.patch.object(cms_revalidate.httpx, "post",
                              return_value=mock.Mock(status_code=401)):
        row.consent_version = 9
        row.save()  # must not raise

    row.refresh_from_db()
    assert row.consent_version == 9


def test_an_unreachable_storefront_never_raises_at_all():
    """End to end through the real transport, with only `httpx` replaced: a dead
    storefront is a log line, not an exception in the Owner's face."""
    import httpx

    with mock.patch.object(cms_revalidate.httpx, "post",
                           side_effect=httpx.ConnectError("down")):
        cms_revalidate._post("http://shop.test/api/revalidate", "s3cret", ["marketing"])


# ── security ────────────────────────────────────────────────────────────────────────

@override_settings(REVALIDATE_SECRET="")
def test_no_secret_means_no_network_at_all():
    """The production default is an empty secret, and it must mean the notifier is off
    rather than the notifier failing loudly."""
    with mock.patch.object(cms_revalidate.threading, "Thread") as thread:
        marketing_revalidate.notify_marketing_changed()
    thread.assert_not_called()


@override_settings(REVALIDATE_SECRET="s3cret", STOREFRONT_BASE_URL="http://shop.test/")
def test_the_marketing_flush_carries_the_secret_in_a_HEADER_and_never_in_the_url():
    with mock.patch.object(cms_revalidate.threading, "Thread") as thread:
        marketing_revalidate.notify_marketing_changed()

    thread.assert_called_once()
    assert thread.call_args.kwargs["daemon"] is True
    url, secret, tags = thread.call_args.kwargs["args"]
    assert url == "http://shop.test/api/revalidate"
    assert "s3cret" not in url, "a secret in a URL lands in every access log there is"
    assert tags == ["marketing"]

    with mock.patch.object(cms_revalidate.httpx, "post") as post:
        post.return_value.status_code = 200
        thread.call_args.kwargs["target"](url, secret, tags)

    post.assert_called_once_with(
        "http://shop.test/api/revalidate",
        json={"tags": ["marketing"]},
        headers={"x-revalidate-secret": "s3cret"},
        timeout=3.0,
    )


def test_a_failure_is_logged_WITHOUT_the_secret(caplog):
    with mock.patch.object(cms_revalidate.httpx, "post",
                           return_value=mock.Mock(status_code=401)):
        cms_revalidate._post("http://shop.test/api/revalidate", "s3cret", ["marketing"])

    assert "s3cret" not in caplog.text
    assert "401" in caplog.text
    assert "marketing" in caplog.text
