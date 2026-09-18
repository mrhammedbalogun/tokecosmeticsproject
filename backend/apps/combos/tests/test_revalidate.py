"""Storefront cache flushes for combo writes.

THREE TAGS, and the reason is in `storefront/src/lib/combos.ts`: the Combo Deals index is
fetched as `["catalog", "combos"]` and a combo's own page as
`["catalog", "combos", "combo:<slug>"]`. The homepage's Combo Deals row is a plain
catalogue fetch. So an edit that reached only `combos` would fix the listing and leave the
combo's own page stale, and one that reached only `combo:<slug>` would fix the page and
leave the shopper looking at the old price on the way to it. Every assertion below names
all three on purpose.

The transport is mocked in every test, so nothing here can reach Vercel — see the same
note on `apps/catalog/tests/test_revalidate.py`. Combos deliberately own no caller of
their own: `apps/combos/revalidate.py` is a tag set on top of `apps.catalog.revalidate`'s
coalescing, which is why the mock below patches the CATALOG module.
"""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

import pytest

from apps.catalog import revalidate as catalog_revalidate
from apps.catalog.factories import ProductVariantFactory
from apps.catalog.tests.autocommit import real_autocommit_connection
from apps.combos.factories import ComboFactory, ComboItemFactory
from apps.combos.models import ComboPrice

pytestmark = pytest.mark.django_db


@pytest.fixture
def sent():
    """Captures the tag lists handed to the storefront caller.

    Patched on `apps.catalog.revalidate`, not on `apps.combos.revalidate`: combos call
    `queue_tags`, and it is the catalogue module that resolves `notify_storefront`.
    """
    with mock.patch.object(catalog_revalidate, "notify_storefront") as m:
        yield m


@pytest.fixture
def flush(django_capture_on_commit_callbacks):
    """Run a write and then its on_commit callbacks — `django_db` rolls back, so without
    this every assertion below would pass vacuously against an empty mock."""
    def run(write):
        with django_capture_on_commit_callbacks(execute=True):
            return write()
    return run


def tags_of(sent_mock) -> set[str]:
    out: set[str] = set()
    for call in sent_mock.call_args_list:
        out.update(call.args[0])
    return out


def expected(slug: str) -> set[str]:
    return {"catalog", "combos", f"combo:{slug}"}


# ── tag mapping ─────────────────────────────────────────────────────────────────────

def test_creating_a_combo_flushes_its_page_the_listing_and_the_homepage(sent, flush):
    combo = flush(ComboFactory)
    assert tags_of(sent) == expected(combo.slug)


def test_editing_a_combo_flushes_the_same_three(sent, flush):
    combo = flush(ComboFactory)
    sent.reset_mock()

    combo.status = "archived"
    flush(lambda: combo.save(update_fields=["status", "updated_at"]))

    assert tags_of(sent) == expected(combo.slug)


def test_deleting_a_combo_flushes_the_same_three(sent, flush):
    combo = flush(ComboFactory)
    slug = combo.slug
    sent.reset_mock()

    flush(combo.delete)

    # The row is gone by the time post_delete runs, but the instance still carries its
    # slug — which is the whole reason the narrow tag is read off the instance and not
    # re-queried. A withdrawn combo's page must not go on being served from cache.
    assert tags_of(sent) == expected(slug)


def test_changing_what_is_IN_the_box_flushes_the_combo(sent, flush):
    """A `ComboItem` write names no combo of its own — the slug is reached through
    `combo.slug`. Nothing in the cached payload changes more visibly than its contents."""
    combo = flush(ComboFactory)
    variant = flush(ProductVariantFactory)
    sent.reset_mock()

    flush(lambda: ComboItemFactory(combo=combo, variant=variant))

    assert tags_of(sent) == expected(combo.slug)


def test_repricing_a_combo_flushes_the_combo(sent, flush, ng):
    combo = flush(ComboFactory)
    sent.reset_mock()

    flush(lambda: ComboPrice.objects.create(
        combo=combo, country=ng, amount=Decimal("18000.00"),
    ))

    assert tags_of(sent) == expected(combo.slug)


def test_withdrawing_a_combo_from_a_market_flushes_it(sent, flush, ng):
    """`available_countries` decides visibility and fires no post_save of its own, so the
    m2m signal is the only thing standing between a withdrawn combo and a TTL of still
    being listed in the market it was pulled from."""
    combo = flush(ComboFactory)
    sent.reset_mock()

    flush(lambda: combo.available_countries.add(ng))
    assert tags_of(sent) == expected(combo.slug)

    sent.reset_mock()
    flush(lambda: combo.available_countries.remove(ng))
    assert tags_of(sent) == expected(combo.slug)


# ── coalescing ──────────────────────────────────────────────────────────────────────

def test_many_combo_writes_in_one_transaction_send_ONE_deduplicated_payload(
    sent, django_capture_on_commit_callbacks,
):
    with django_capture_on_commit_callbacks(execute=True):
        combos = [ComboFactory() for _ in range(5)]
        assert sent.call_count == 0, "must not fire mid-transaction"

    assert sent.call_count == 1
    payload = sent.call_args.args[0]
    assert len(payload) == len(set(payload)), "tags must be deduplicated"
    # `catalog` and `combos` are shared by all five and appear once; each combo still
    # gets its own narrow tag, because each has its own page to flush.
    assert payload.count("catalog") == 1
    assert payload.count("combos") == 1
    assert set(payload) == {"catalog", "combos", *(f"combo:{c.slug}" for c in combos)}
    assert payload == sorted(payload), "a stable payload, so a test can assert it"


def test_a_rolled_back_combo_flushes_nothing(sent):
    from django.db import transaction

    class Rollback(Exception):
        pass

    with pytest.raises(Rollback):
        with transaction.atomic():
            ComboFactory()
            raise Rollback

    assert sent.call_count == 0


# ── autocommit ──────────────────────────────────────────────────────────────────────

def test_a_combo_save_in_autocommit_flushes_AT_ONCE(sent, monkeypatch):
    """Combos ride `queue_tags`, so they inherited its autocommit bug whole: a combo
    edited from a shell or a management command flushed nothing at all. See
    `apps/catalog/tests/autocommit.py` for what the connection underneath this is."""
    with real_autocommit_connection(monkeypatch):
        combo = ComboFactory()

    assert sent.call_count == 1
    assert sent.call_args.args[0] == ["catalog", f"combo:{combo.slug}", "combos"]


def test_autocommit_combo_writes_lose_no_tag(sent, monkeypatch):
    with real_autocommit_connection(monkeypatch):
        first = ComboFactory()
        second = ComboFactory()

    assert [call.args[0] for call in sent.call_args_list] == [
        ["catalog", f"combo:{first.slug}", "combos"],
        ["catalog", f"combo:{second.slug}", "combos"],
    ]


# ── failure handling ────────────────────────────────────────────────────────────────

def test_a_failing_flush_never_costs_the_combo(sent, django_capture_on_commit_callbacks):
    """The business operation is the bundle. Cache invalidation is a side effect, and a
    side effect must not be able to roll one back."""
    sent.side_effect = RuntimeError("storefront on fire")

    with django_capture_on_commit_callbacks(execute=True):
        combo = ComboFactory(slug="survivor-combo")

    combo.refresh_from_db()
    assert combo.slug == "survivor-combo"


def test_a_failing_flush_never_costs_an_autocommit_combo_either(sent, monkeypatch):
    """The same guarantee on the path that delivers INLINE. Here the notifier runs inside
    the caller's own stack rather than after it, so a raise would land on the operator."""
    sent.side_effect = RuntimeError("storefront on fire")

    with real_autocommit_connection(monkeypatch):
        combo = ComboFactory(slug="survivor-autocommit")

    combo.refresh_from_db()
    assert combo.slug == "survivor-autocommit"
