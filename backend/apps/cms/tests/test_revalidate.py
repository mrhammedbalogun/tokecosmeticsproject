"""The storefront revalidation notifier (Phase 3, 2026-08-06): CMS writes flush the
storefront's "cms" cache tag instantly; no secret means no calls and the storefront's
own 60-second window covers freshness."""
from unittest import mock

import pytest
from django.test import override_settings

from apps.cms import revalidate
from apps.cms.models import Banner

pytestmark = pytest.mark.django_db


@override_settings(REVALIDATE_SECRET="")
def test_no_secret_means_no_network_at_all():
    with mock.patch.object(revalidate.threading, "Thread") as thread:
        revalidate.notify_storefront(["cms"])
    thread.assert_not_called()


@override_settings(REVALIDATE_SECRET="s3cret", STOREFRONT_BASE_URL="http://shop.test/")
def test_posts_the_tags_with_the_shared_secret_off_thread():
    with mock.patch.object(revalidate.threading, "Thread") as thread:
        revalidate.notify_storefront(["cms"])
    thread.assert_called_once()
    assert thread.call_args.kwargs["daemon"] is True
    target, (url, secret, tags) = (
        thread.call_args.kwargs["target"],
        thread.call_args.kwargs["args"],
    )
    assert url == "http://shop.test/api/revalidate"  # trailing slash normalised
    with mock.patch.object(revalidate.httpx, "post") as post:
        post.return_value.status_code = 200
        target(url, secret, tags)
    post.assert_called_once_with(
        "http://shop.test/api/revalidate",
        json={"tags": ["cms"]},
        headers={"x-revalidate-secret": "s3cret"},
        timeout=3.0,
    )


@override_settings(REVALIDATE_SECRET="s3cret")
def test_an_unreachable_storefront_never_raises():
    with mock.patch.object(revalidate.httpx, "post", side_effect=revalidate.httpx.ConnectError("down")):
        revalidate._post("http://shop.test/api/revalidate", "s3cret", ["cms"])  # no exception


@override_settings(REVALIDATE_SECRET="s3cret")
def test_a_banner_write_fires_the_notifier():
    # Signals are wired in CmsConfig.ready() for every write path, not just the admin API.
    with mock.patch.object(revalidate, "notify_storefront") as notify:
        banner = Banner.objects.create(title="Sale", placement="strip")
    notify.assert_called_with(["cms"])
    with mock.patch.object(revalidate, "notify_storefront") as notify:
        banner.delete()
    notify.assert_called_with(["cms"])
