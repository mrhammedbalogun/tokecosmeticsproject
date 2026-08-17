"""The edge-trigger safety net on the two migrated beat alerts.

WHY THIS FILE EXISTS. `low_stock_digest` and `monitor_gig_wallet` are edge-triggered:
each records "they have been told" in a `SiteSetting` and then stays quiet until the
situation CHANGES. Before this feature they called `send_email` synchronously, so a
failure raised, the state row was never written, and the next beat run retried.

Moving them onto `notify_staff` made sending asynchronous, and the naive version wrote
the state unconditionally — which converts one broker blip into an alert nobody ever
receives, because the low list stays identical and the wallet balance stays below
threshold. That is a narrower rerun of the exact `DEFAULT_FROM_EMAIL` bug this whole
feature was built to end, reintroduced in the two events it was built to rescue.
"""
import pytest
from django.core import mail

from apps.core.models import SiteSetting
from apps.notifications.models import NotificationRecipient

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []


def _broker_down(monkeypatch, module):
    """Make the enqueue fail the way a Redis outage does."""
    def boom(*args, **kwargs):
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(module.send_email_task, "delay", boom)


# ── low stock ───────────────────────────────────────────────────────────────────────

def test_a_failed_enqueue_leaves_the_digest_free_to_retry(monkeypatch):
    from apps.catalog.factories import ProductVariantFactory
    from apps.inventory.factories import StockItemFactory, WarehouseFactory
    from apps.inventory.tasks import _DIGEST_STATE_KEY, low_stock_digest
    import apps.notifications.staff as staff_mod

    NotificationRecipient.objects.create(event="inventory.low_stock", email="s@x.com")
    StockItemFactory(variant=ProductVariantFactory(sku="A-1"), warehouse=WarehouseFactory(),
                     quantity=1, low_stock_threshold=5)

    _broker_down(monkeypatch, staff_mod)
    low_stock_digest()

    assert mail.outbox == []
    # The signature must NOT be recorded — otherwise the identical list compares equal on
    # every later run and the digest is silent forever.
    assert not SiteSetting.objects.filter(key=_DIGEST_STATE_KEY).exists()

    # Broker back: the very next run delivers.
    monkeypatch.undo()
    assert low_stock_digest() == 1
    assert len(mail.outbox) == 1
    assert SiteSetting.objects.filter(key=_DIGEST_STATE_KEY).exists()


def test_no_subscribers_still_records_the_signature(monkeypatch):
    """`sent == 0` because nobody is subscribed is a CONFIGURATION, not a failure. Holding
    the state back there would re-render an email into the void every hour forever."""
    from apps.catalog.factories import ProductVariantFactory
    from apps.inventory.factories import StockItemFactory, WarehouseFactory
    from apps.inventory.tasks import _DIGEST_STATE_KEY, low_stock_digest

    StockItemFactory(variant=ProductVariantFactory(sku="A-1"), warehouse=WarehouseFactory(),
                     quantity=1, low_stock_threshold=5)

    low_stock_digest()

    assert mail.outbox == []
    assert SiteSetting.objects.filter(key=_DIGEST_STATE_KEY).exists()


# ── GIG wallet ──────────────────────────────────────────────────────────────────────

def test_a_failed_wallet_enqueue_does_not_arm_the_low_state(monkeypatch):
    """Worse consequences than the digest: re-arming needs the balance to climb back
    ABOVE the threshold and dip again. Record `low` on a run that sent nothing and the
    alert is lost until someone tops the wallet up — which nobody will, because the alert
    asking them to is the thing that went missing."""
    from decimal import Decimal

    import apps.delivery.tasks as delivery_tasks
    import apps.notifications.staff as staff_mod
    from apps.delivery.tasks import _WALLET_ALERT_STATE_KEY, monitor_gig_wallet

    NotificationRecipient.objects.create(event="delivery.gig_wallet_low", email="o@x.com")
    monkeypatch.setattr(delivery_tasks, "GigError", Exception, raising=False)
    monkeypatch.setattr(
        "apps.delivery.gig.capture.wallet_balance", lambda refresh=False: Decimal("10000")
    )

    _broker_down(monkeypatch, staff_mod)
    result = monitor_gig_wallet.apply().result

    assert mail.outbox == []
    assert result["alerted"] is False
    assert result.get("enqueue_failed") is True
    row = SiteSetting.objects.filter(key=_WALLET_ALERT_STATE_KEY).first()
    assert row is None or row.value != "low"


def test_the_wallet_alert_lands_on_the_next_run_after_the_broker_recovers(monkeypatch):
    from decimal import Decimal

    import apps.delivery.tasks as delivery_tasks
    import apps.notifications.staff as staff_mod
    from apps.delivery.tasks import _WALLET_ALERT_STATE_KEY, monitor_gig_wallet

    NotificationRecipient.objects.create(event="delivery.gig_wallet_low", email="o@x.com")
    monkeypatch.setattr(delivery_tasks, "GigError", Exception, raising=False)
    monkeypatch.setattr(
        "apps.delivery.gig.capture.wallet_balance", lambda refresh=False: Decimal("10000")
    )

    # A TOGGLE rather than `monkeypatch.undo()`, which reverts EVERY patch this test made
    # — including the wallet-balance stub, sending the second run at the real GIG API.
    real_delay = staff_mod.send_email_task.delay
    broker = {"down": True}

    def maybe(*args, **kwargs):
        if broker["down"]:
            raise ConnectionError("broker unreachable")
        return real_delay(*args, **kwargs)

    monkeypatch.setattr(staff_mod.send_email_task, "delay", maybe)

    monitor_gig_wallet.apply()          # blip: nothing sent, state not armed
    broker["down"] = False

    result = monitor_gig_wallet.apply().result
    assert result["alerted"] is True
    assert len(mail.outbox) == 1
    assert SiteSetting.objects.get(key=_WALLET_ALERT_STATE_KEY).value == "low"
