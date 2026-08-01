"""LegacyIdentity: the idempotency key for the cutover, and Plan-23's order link."""

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import STORE_PRECEDENCE, LegacyIdentity, LegacyStore, User, best_store

pytestmark = pytest.mark.django_db


def _user(email="a@example.com"):
    return User.objects.create_user(email=email, password="irrelevant-here-123")


def test_THE_SAME_WP_ID_ON_TWO_STORES_IS_TWO_DIFFERENT_PEOPLE():
    # NG user 42 and intl user 42 are unrelated humans. A unique constraint on wp_user_id
    # alone would reject the second one, and the "fix" someone would reach for under time
    # pressure — skip the duplicate — would silently drop a real customer.
    ng, intl = _user("ng@example.com"), _user("intl@example.com")
    LegacyIdentity.objects.create(user=ng, store=LegacyStore.NG, wp_user_id=42)
    LegacyIdentity.objects.create(user=intl, store=LegacyStore.INTL, wp_user_id=42)

    assert LegacyIdentity.objects.filter(wp_user_id=42).count() == 2


def test_the_same_wp_id_twice_on_one_store_is_rejected():
    user = _user()
    LegacyIdentity.objects.create(user=user, store=LegacyStore.NG, wp_user_id=42)
    with pytest.raises(IntegrityError), transaction.atomic():
        LegacyIdentity.objects.create(user=_user("b@example.com"), store=LegacyStore.NG, wp_user_id=42)


def test_ONE_USER_HOLDS_UP_TO_THREE_IDENTITIES():
    # The 17 merged customers. A unique constraint on `user` would have made this
    # impossible and forced the merge to throw away two of the three WordPress ids —
    # taking their order history on those stores with it in Plan-23.
    user = _user()
    for store in LegacyStore:
        LegacyIdentity.objects.create(user=user, store=store, wp_user_id=7)

    assert user.legacy_identities.count() == 3


def test_identities_go_when_the_user_does():
    user = _user()
    LegacyIdentity.objects.create(user=user, store=LegacyStore.NG, wp_user_id=1)
    user.delete()
    assert LegacyIdentity.objects.count() == 0


# ── collision precedence ─────────────────────────────────────────────────────────────────


def test_THE_LIVE_STORES_BEAT_THE_DEAD_ONE():
    # A customer on both NG-current and NG-old keeps their CURRENT name and password. The
    # old store has taken no orders since November 2025, so its copy of them is the stale
    # one — restoring it would look to the customer like the new site forgot a password
    # change they made.
    assert best_store([LegacyStore.NG_OLD, LegacyStore.NG]) == LegacyStore.NG
    assert best_store([LegacyStore.NG_OLD, LegacyStore.INTL]) == LegacyStore.INTL


def test_ng_current_outranks_intl():
    assert best_store([LegacyStore.INTL, LegacyStore.NG]) == LegacyStore.NG


def test_precedence_is_order_independent():
    # The importer sees stores in whatever order it reads them. If the answer depended on
    # that, the staging run and the cutover delta run could disagree about the same
    # customer — and the second one would overwrite the first with a different person's
    # name.
    both = [LegacyStore.NG, LegacyStore.INTL, LegacyStore.NG_OLD]
    assert best_store(both) == best_store(list(reversed(both))) == LegacyStore.NG


@pytest.mark.parametrize("stores", [[], ["not_a_store"], ["", None]])
def test_best_store_of_nothing_recognisable_is_empty_not_a_crash(stores):
    assert best_store(stores) == ""


def test_every_store_appears_in_the_precedence_list():
    # A store added to LegacyStore without a precedence entry would silently always lose,
    # so its customers would never win a collision and would keep another store's
    # password. Cheap tripwire for a change made two files away.
    assert set(STORE_PRECEDENCE) == set(LegacyStore)


def test_the_two_replaced_columns_are_gone():
    # Plan-22 ruling 3: two columns for three stores. If a future merge resurrects them,
    # the importer would have two places to write provenance and they would drift.
    fields = {f.name for f in User._meta.get_fields()}
    assert "legacy_wp_id" not in fields
    assert "legacy_wp_id_intl" not in fields
    assert "legacy_source" in fields
