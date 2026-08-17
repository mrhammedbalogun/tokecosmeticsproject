"""The low-stock digest only speaks when something changed.

It runs hourly. With no stock in the system that was harmless; with a real catalogue and a
handful of chronically low SKUs it would have sent the identical list 24 times a day, and
the reliable result of that is a mail rule that hides the one message that mattered.
"""
import pytest
from django.core import mail

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import SiteSetting
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.tasks import low_stock_digest

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _somebody_is_subscribed():
    """The digest is addressed to the "Low stock" list on the Email Notifications screen
    (`apps/notifications/events.py`) rather than to `DEFAULT_FROM_EMAIL`, which had no
    inbox. With an empty list it correctly sends nothing — so these tests, which are
    about WHEN the digest speaks and not about who hears it, need one subscriber."""
    from django.utils import timezone

    from apps.notifications.models import NotificationRecipient

    # `confirmed_at` because an external address receives nothing until it has clicked its
    # confirmation link. These tests are about WHEN the digest speaks, not about the
    # confirmation gate (`apps/notifications/tests/test_confirmation.py` owns that), so
    # they need a subscriber who is actually live.
    NotificationRecipient.objects.create(
        event="inventory.low_stock", email="stock@x.com", confirmed_at=timezone.now()
    )



@pytest.fixture(autouse=True)
def _locmem(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []


def _low(sku: str, quantity: int = 1, warehouse=None):
    return StockItemFactory(
        variant=ProductVariantFactory(sku=sku),
        warehouse=warehouse or WarehouseFactory(),
        quantity=quantity,
        low_stock_threshold=5,
    )


def test_the_first_dip_sends():
    _low("A-1")

    assert low_stock_digest() == 1
    assert len(mail.outbox) == 1


def test_AN_UNCHANGED_LIST_SENDS_NOTHING_THE_SECOND_TIME():
    """The whole fix: 24 runs a day, one email."""
    _low("A-1")
    low_stock_digest()
    mail.outbox = []

    for _ in range(5):
        assert low_stock_digest() == 1

    assert mail.outbox == []


def test_a_newly_low_item_sends_again_and_says_which():
    warehouse = WarehouseFactory()
    _low("A-1", warehouse=warehouse)
    low_stock_digest()
    mail.outbox = []

    _low("B-2", warehouse=warehouse)
    low_stock_digest()

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "Newly low" in body and "B-2" in body
    # And the full picture is still there, so the mail is actionable on its own.
    assert "A-1" in body


def test_DRIFTING_WITHIN_THE_LOW_BAND_DOES_NOT_RE_ALERT():
    """5 → 4 → 3 is the same news three times, and re-sending it is what trains somebody
    to filter this mail."""
    item = _low("A-1", quantity=4)
    low_stock_digest()
    mail.outbox = []

    item.quantity = 3
    item.save(update_fields=["quantity"])

    assert low_stock_digest() == 1
    assert mail.outbox == []


def test_RUNNING_OUT_ENTIRELY_DOES_RE_ALERT():
    """Zero changes what a customer can buy, so it is part of the fingerprint."""
    item = _low("A-1", quantity=3)
    low_stock_digest()
    mail.outbox = []

    item.quantity = 0
    item.save(update_fields=["quantity"])
    low_stock_digest()

    assert len(mail.outbox) == 1


def test_recovery_is_recorded_silently_and_arms_the_next_dip():
    """'Nothing is low any more' is good news nobody needs interrupting for — but the
    state must reset, or the next dip would be compared against a stale list."""
    item = _low("A-1")
    low_stock_digest()
    mail.outbox = []

    item.quantity = 100
    item.save(update_fields=["quantity"])
    assert low_stock_digest() == 0
    assert mail.outbox == []

    item.quantity = 1
    item.save(update_fields=["quantity"])
    low_stock_digest()

    assert len(mail.outbox) == 1


def test_the_state_is_persisted_in_the_database_not_the_cache():
    """CACHE_BACKEND is unset in production, so the default is per-process LocMemCache —
    two Celery workers would each believe they had never sent anything."""
    _low("A-1")
    low_stock_digest()

    assert SiteSetting.objects.filter(
        key="inventory.low_stock_digest.last_signature"
    ).exists()
