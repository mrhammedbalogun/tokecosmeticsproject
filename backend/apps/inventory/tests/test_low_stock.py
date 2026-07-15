import pytest
from django.core import mail

from apps.inventory.factories import StockItemFactory
from apps.inventory.tasks import low_stock_digest


@pytest.mark.django_db
def test_low_stock_digest_emails_when_below_threshold(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []
    StockItemFactory(quantity=2, reserved=0, low_stock_threshold=5)   # low
    StockItemFactory(quantity=50, reserved=0, low_stock_threshold=5)  # fine
    sent = low_stock_digest()
    assert sent == 1                    # one item in the digest
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_low_stock_digest_silent_when_all_ok(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []
    StockItemFactory(quantity=50, reserved=0, low_stock_threshold=5)
    assert low_stock_digest() == 0
    assert len(mail.outbox) == 0
