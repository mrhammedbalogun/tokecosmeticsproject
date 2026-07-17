"""Transactional emails. These render the real templates against a real order — a
template that renders only under a mock is a template that breaks in production."""
import pytest
from django.core import mail

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.orders.state import transition_by_id

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


def _order(number="TC-500001", status="pending_payment", **kw):
    ng = Country.objects.get(code="NG")
    order = OrderFactory(number=number, country=ng, currency=ng.currency, status=status,
                         email="buyer@x.com", grand_total="1000.00", subtotal="900.00",
                         shipping_total="100.00", delivery_option_name="Lagos Island Same-Day",
                         shipping_address={"line1": "1 Awolowo Rd", "city": "Ikoyi",
                                           "region": "Lagos", "country": "NG"}, **kw)
    OrderItem.objects.create(order=order, product_name="Shea Butter", variant_name="200ml",
                             sku="SB-200", unit_price="450.00", line_total="900.00", quantity=2)
    return order


def test_confirmation_email_is_sent_when_payment_is_verified(django_capture_on_commit_callbacks):
    order = _order()

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert order.number in msg.subject
    assert msg.to == ["buyer@x.com"]  # the snapshot, not the account's current address
    assert "Shea Butter" in msg.body
    assert "₦1,000.00" in msg.body  # formatted via the currency's decimal_places


def test_confirmation_also_fires_for_a_late_payment_after_expiry(
    django_capture_on_commit_callbacks,
):
    """expired -> processing is the late-payment re-reserve path. That customer paid and
    is owed the same email as everyone else — keying effects on the destination status
    (not the pair) is what stops them being silently skipped."""
    order = _order(number="TC-500002", status="expired")

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    assert len(mail.outbox) == 1
    assert order.number in mail.outbox[0].subject


def test_shipped_email_carries_the_tracking_details(django_capture_on_commit_callbacks):
    order = _order(number="TC-500003", status="processing",
                   tracking_carrier="GIG Logistics", tracking_number="GIG123456")

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "shipped")

    body = mail.outbox[0].body
    assert "GIG Logistics" in body
    assert "GIG123456" in body


def test_shipped_email_omits_tracking_when_there_is_none(django_capture_on_commit_callbacks):
    """Tracking is optional; the template must not render a dangling empty label."""
    order = _order(number="TC-500004", status="processing")

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "shipped")

    assert "Tracking" not in mail.outbox[0].body


def test_delivered_email_renders(django_capture_on_commit_callbacks):
    order = _order(number="TC-500005", status="shipped")

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "delivered")

    assert len(mail.outbox) == 1
    assert order.number in mail.outbox[0].subject


def test_no_email_for_internal_moves(django_capture_on_commit_callbacks):
    """Customers should not be told the order is `on_hold` or `expired` — those are our
    words for our problems."""
    order = _order(number="TC-500006", status="processing")

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "on_hold")

    assert mail.outbox == []


def test_confirmation_carries_a_tracking_link_that_actually_works(
    django_capture_on_commit_callbacks,
):
    """Asserts the token in the link resolves to THIS order — not merely that some URL
    made it into the body. A dead link in a confirmation email is a support ticket."""
    import re

    from apps.orders.tokens import read_tracking_token

    order = _order(number="TC-500009")

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    match = re.search(r"token=([A-Za-z0-9_\-:]+)", mail.outbox[0].body)
    assert match, "confirmation email must contain a tracking link"
    assert read_tracking_token(match.group(1)) == "TC-500009"


def test_html_emails_declare_utf8_so_the_naira_sign_survives(django_capture_on_commit_callbacks):
    """Django sets a utf-8 MIME header, but not every client honours it over the
    document's own declaration — and an HTML email with no charset gets read as latin-1,
    turning every ₦ into "â‚¦". That's the symbol on nearly every email we send."""
    order = _order(number="TC-500008")

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    html = mail.outbox[0].alternatives[0][0]
    assert 'charset="utf-8"' in html.lower()
    assert "₦1,000.00" in html


def test_emails_are_not_sent_before_the_transaction_commits():
    """The whole reason effects are deferred: no capture fixture, no commit, no email."""
    order = _order(number="TC-500007")

    transition_by_id(order.pk, "processing")

    assert mail.outbox == []  # the enqueue is registered, waiting on a commit that never comes
