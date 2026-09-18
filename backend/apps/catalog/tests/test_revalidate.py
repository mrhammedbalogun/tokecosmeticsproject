"""Storefront cache flushes for catalogue, redirect and region writes.

Combos have their own module beside this one (`apps/combos/tests/test_revalidate.py`),
because the tags they own are theirs; what they share with this file is `queue_tags`.

Every test mocks `notify_storefront`, so nothing here can reach Vercel. That is not only
hygiene: `REVALIDATE_SECRET` is set on a developer machine, and an unmocked receiver
firing from an unrelated test is how this suite would start POSTing at the live shop (the
hazard `apps/core/revalidate.py` already documents for BusinessDecisions).
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.db import transaction
from django.test import override_settings

from apps.catalog import revalidate as catalog_revalidate
from apps.catalog.models import Brand, Category, Collection, Product
from apps.catalog.tests.autocommit import real_autocommit_connection
from apps.cms import revalidate as cms_revalidate
from apps.core import revalidate as core_revalidate
from apps.core.models import Redirect, Region

pytestmark = pytest.mark.django_db


@pytest.fixture
def sent():
    """Captures the tag lists handed to the storefront caller."""
    # Each module imported `notify_storefront` BY VALUE, so patching one does not reach
    # the others — patching only `cms` silently let core's receivers call the real thing.
    with mock.patch.object(cms_revalidate, "notify_storefront") as m, \
            mock.patch.object(catalog_revalidate, "notify_storefront", m), \
            mock.patch.object(core_revalidate, "notify_storefront", m):
        yield m


@pytest.fixture
def flush(django_capture_on_commit_callbacks):
    """Run a write and then its on_commit callbacks.

    Necessary, not incidental: `pytest.mark.django_db` wraps each test in a transaction it
    rolls back, so `transaction.on_commit` would otherwise never fire and every assertion
    below would pass vacuously against an empty mock. This executes the callbacks the way
    a real COMMIT would.
    """
    def run(write):
        with django_capture_on_commit_callbacks(execute=True):
            return write()
    return run


def tags_of(sent_mock) -> set[str]:
    out: set[str] = set()
    for call in sent_mock.call_args_list:
        out.update(call.args[0])
    return out


# ── tag mapping ─────────────────────────────────────────────────────────────────────

def test_a_product_write_flushes_the_listings_and_its_own_page(sent, flush):
    product = flush(lambda: Product.objects.create(name="Glow Serum", slug="glow-serum"))
    tags = tags_of(sent)

    # BOTH, because the storefront tags a detail fetch ["catalog", "product:<slug>"] and
    # every grid fetch ["catalog"] — a price edit has to reach the grid as well.
    assert "catalog" in tags
    assert f"product:{product.slug}" in tags


@pytest.mark.parametrize("factory", [
    lambda: Category.objects.create(name="Face", slug="face"),
    lambda: Brand.objects.create(name="Toke", slug="toke"),
    lambda: Collection.objects.create(name="Best", slug="best"),
])
def test_taxonomy_writes_flush_only_the_broad_tag(factory, sent, flush):
    flush(factory)
    tags = tags_of(sent)

    assert "catalog" in tags
    # No product is named by a category rename, so no narrow tag is invented for one.
    assert not any(t.startswith("product:") for t in tags)


def test_a_redirect_write_flushes_the_redirect_table(sent, flush):
    flush(lambda: Redirect.objects.create(old_path="/old", new_path="/new", status_code=301))
    assert tags_of(sent) == {"redirects"}


def test_a_region_write_flushes_the_region_table(sent, flush):
    flush(lambda: Region.objects.create(country_code="NG", name="Lagos", level="state"))
    assert tags_of(sent) == {"regions"}


def test_deleting_a_product_flushes_too(sent, flush):
    product = flush(lambda: Product.objects.create(name="Gone", slug="gone-soon"))
    sent.reset_mock()
    flush(product.delete)

    assert "catalog" in tags_of(sent)


# ── coalescing: the import-loop guard ───────────────────────────────────────────────

def test_many_writes_in_one_transaction_send_ONE_deduplicated_payload(
    sent, django_capture_on_commit_callbacks,
):
    # The shape of `migration_wp` re-importing the catalogue. Per-save notification would
    # have started a thread each; this must collapse to a single POST.
    with django_capture_on_commit_callbacks(execute=True):
        for i in range(25):
            Product.objects.create(name=f"P{i}", slug=f"p-{i}")
        assert sent.call_count == 0, "must not fire mid-transaction"

    assert sent.call_count == 1
    payload = sent.call_args.args[0]
    assert len(payload) == len(set(payload)), "tags must be deduplicated"
    assert payload.count("catalog") == 1


def test_tags_are_sorted_so_the_payload_is_stable(sent, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        Product.objects.create(name="B", slug="bbb")
        Product.objects.create(name="A", slug="aaa")

    payload = sent.call_args.args[0]
    assert payload == sorted(payload)


def test_nothing_is_sent_when_a_transaction_rolls_back(sent):
    class Rollback(Exception):
        pass

    with pytest.raises(Rollback):
        with transaction.atomic():
            Product.objects.create(name="Doomed", slug="doomed")
            raise Rollback

    # on_commit never runs, so a write that did not happen cannot flush a cache.
    assert sent.call_count == 0


# ── the transport itself ────────────────────────────────────────────────────────────

@override_settings(REVALIDATE_SECRET="")
def test_no_secret_configured_means_no_request_at_all():
    with mock.patch.object(cms_revalidate, "_post") as post:
        cms_revalidate.notify_storefront(["catalog"])
    assert post.call_count == 0


@override_settings(REVALIDATE_SECRET="s3cret", STOREFRONT_BASE_URL="http://shop.test/")
def test_url_auth_header_and_payload():
    with mock.patch("apps.cms.revalidate.httpx.post") as post:
        cms_revalidate._post("http://shop.test/api/revalidate", "s3cret", ["catalog", "cms"])

    url = post.call_args.args[0]
    kwargs = post.call_args.kwargs
    assert url == "http://shop.test/api/revalidate"
    assert kwargs["headers"] == {"x-revalidate-secret": "s3cret"}
    assert kwargs["json"] == {"tags": ["catalog", "cms"]}
    assert kwargs["timeout"] == 3.0, "the timeout must stay bounded"


def test_a_network_failure_is_swallowed_and_logged_without_the_secret(caplog):
    import httpx

    with mock.patch("apps.cms.revalidate.httpx.post", side_effect=httpx.ConnectError("down")):
        cms_revalidate._post("http://shop.test/api/revalidate", "s3cret", ["catalog"])

    assert "s3cret" not in caplog.text
    assert "unreachable" in caplog.text


def test_a_non_200_is_swallowed_and_logged_without_the_secret(caplog):
    with mock.patch("apps.cms.revalidate.httpx.post",
                    return_value=mock.Mock(status_code=401)):
        cms_revalidate._post("http://shop.test/api/revalidate", "s3cret", ["catalog"])

    assert "s3cret" not in caplog.text
    assert "401" in caplog.text


# ── autocommit: the half the suite could not see ────────────────────────────────────
#
# Read `apps/catalog/tests/autocommit.py` first — it explains why these do not use
# `django_db(transaction=True)` and what the connection underneath them really is.

def test_a_product_save_in_autocommit_flushes_AT_ONCE(sent, monkeypatch):
    """The regression this file exists for.

    With the hook registered before the tag set was filled, this produced NOTHING: no
    call, no log line, no failed request. Every Celery task, management command, shell
    session and dev/staging request was in exactly this state.
    """
    with real_autocommit_connection(monkeypatch):
        product = Product.objects.create(name="Autocommit Serum", slug="autocommit-serum")

    assert sent.call_count == 1, "an autocommit save must deliver, and deliver once"
    assert sent.call_args.args[0] == ["catalog", f"product:{product.slug}"]


def test_autocommit_loses_no_tag_across_separate_saves(sent, monkeypatch):
    """Each save is its own transaction, so each one delivers — none is swallowed by a
    pending set left over from the last."""
    with real_autocommit_connection(monkeypatch):
        Product.objects.create(name="A", slug="auto-a")
        Product.objects.create(name="B", slug="auto-b")
        Category.objects.create(name="Face", slug="auto-face")

    assert [call.args[0] for call in sent.call_args_list] == [
        ["catalog", "product:auto-a"],
        ["catalog", "product:auto-b"],
        ["catalog"],
    ]


def test_autocommit_payloads_are_sorted_and_deduplicated_too(sent, monkeypatch):
    with real_autocommit_connection(monkeypatch):
        catalog_revalidate.queue_tags(["product:z", "catalog", "catalog", "product:z"])

    assert sent.call_args.args[0] == ["catalog", "product:z"]


def test_manual_transaction_management_refuses_to_flush_early(sent, monkeypatch, caplog):
    """The third state: not in an atomic block, and not in autocommit either.

    The write is NOT committed and Django's `on_commit` raises rather than accepting a
    hook. Flushing anyway would advertise a row a rollback could still take back, so the
    rule is to say so and let the TTL cover it — never to guess.
    """
    with caplog.at_level("WARNING"):
        with real_autocommit_connection(monkeypatch, autocommit=False):
            catalog_revalidate.queue_tags(["catalog", "product:held"])

    assert sent.call_count == 0
    assert "manual transaction management" in caplog.text
    assert "'catalog', 'product:held'" in caplog.text


def test_a_failing_flush_never_costs_the_write(sent, django_capture_on_commit_callbacks):
    # The business operation is the product. Cache invalidation is a side effect, and a
    # side effect must not be able to roll one back.
    sent.side_effect = RuntimeError("storefront on fire")

    # No exception escapes: `_flush` swallows and logs, because on_commit runs after the
    # write is durable and a cache side effect must not become a 500 for the operator.
    with django_capture_on_commit_callbacks(execute=True):
        Product.objects.create(name="Survivor", slug="survivor")

    assert Product.objects.filter(slug="survivor").exists()
