"""What the two programme emails may and may not contain.

THE FIRST TEST IN THIS FILE IS LOAD-BEARING FOR THE PERMISSION MODEL, not just for the
copy. `apps/accounts/rbac.py` lets a Manager — not only the Owner — decide who is
subscribed to this alert, and the entire justification for that widening is that the
alert names a student and their school and carries no way to contact them. An external
subscriber has no admin login and no second factor; if this mail ever grew an email
address or a phone number, the grant would silently become "a Manager may forward a
named young person's contact details to any address they can type".

So this is the test that has to fail if somebody helpfully adds the phone number to the
staff alert "so we can call them faster". Careers has the same test for the same reason
(`apps/careers/tests/test_emails.py`).
"""
import re

import pytest
from django.core import mail

from apps.core.models import Country
from apps.entrepreneurship.emails import (
    EVENT_APPLICATION_RECEIVED,
    notify_application_received,
)
from apps.entrepreneurship.factories import application
from apps.notifications.models import NotificationRecipient

pytestmark = pytest.mark.django_db


@pytest.fixture
def subscriber(db):
    """One confirmed external address on the programme alert — the exact shape the
    widened scope is about: no account, no second factor, receives the mail."""
    row = NotificationRecipient.objects.create(
        event=EVENT_APPLICATION_RECEIVED, email="programme@example.com"
    )
    # Confirmed by hand rather than through the click flow: this file is about the
    # CONTENT of the mail, and the consent gate has its own tests.
    from django.utils import timezone

    row.confirmed_at = timezone.now()
    row.save(update_fields=["confirmed_at"])
    return row


def test_THE_STAFF_ALERT_CARRIES_NO_CONTACT_DETAILS(subscriber, settings):
    """The promise `rbac.py` makes when it grants a Manager this list.

    The mail may name the student and where they study. It may NOT carry anything that
    would let the recipient contact them directly, because the recipient may be an
    address with no login behind it.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    row = application(
        email="chidinma@example.com",
        phone="+2348023900964",
        motivation="I already sell to my hostel and I want to do it properly.",
    )
    mail.outbox.clear()

    notify_application_received(row.pk)

    staff_mails = [m for m in mail.outbox if subscriber.email in m.to]
    assert staff_mails, "the subscribed address was not emailed at all"

    for message in staff_mails:
        haystack = "\n".join(
            [message.subject, message.body, *(body for body, _ in message.alternatives)]
        )
        # The three things that would turn this alert into a leak.
        assert row.email not in haystack, "the staff alert leaked the student's email"
        assert "8023900964" not in haystack, "the staff alert leaked the student's phone"
        assert "hostel" not in haystack, "the staff alert leaked the motivation letter"
        # And the two it is FOR — asserted so a future edit cannot satisfy this test by
        # emptying the mail out.
        assert row.full_name in haystack
        assert row.institution in haystack


def test_the_applicant_confirmation_promises_no_money_and_asks_for_none(settings):
    """Two failure modes this mail must not have.

    A number in it is a commitment an automated message made to a student who will quote
    it back. And because the programme's whole shape — "we give you stock, you pay us
    from sales" — is the shape of every advance-fee scam a student has been warned
    about, the mail says plainly that we never ask for money. That sentence is the
    cheapest fraud control available and it belongs in the first mail we ever send them.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    row = application()
    mail.outbox.clear()

    notify_application_received(row.pk)

    to_student = [m for m in mail.outbox if row.email in m.to]
    assert to_student, "the student was not sent a confirmation"

    for body in [to_student[0].body, *(b for b, _ in to_student[0].alternatives)]:
        assert "never ask you to pay" in body.lower()

    # No commission rate, no stock value, no target — the numbers a student would hold
    # us to are decided in a conversation, not in a template.
    #
    # THE PLAIN-TEXT PART ONLY, and asserted as a PATTERN rather than as a bare "%":
    # the HTML part is a responsive email shell whose <style> block is full of
    # `width: 100%`, so a naive substring check fails on the layout instead of on the
    # copy. What is actually forbidden is a FIGURE — "20%", "₦50,000" — which is what
    # these two patterns look for.
    text = to_student[0].body
    assert not re.search(r"\d+\s*%", text), f"the mail quotes a percentage: {text}"
    assert not re.search(r"[₦$£]\s*[\d,]+", text), f"the mail quotes an amount: {text}"


def test_a_missing_row_is_a_no_op_not_a_traceback(settings):
    """Called from a post-commit hook and from Celery alike, so a row deleted in the
    seconds after it was written must not raise."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    notify_application_received(999999)  # must not raise


def test_the_country_is_named_for_a_reader_who_runs_four_markets(subscriber, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    row = application(country=Country.objects.get(code="GB"), email="uk@example.com")
    mail.outbox.clear()

    notify_application_received(row.pk)

    staff_mails = [m for m in mail.outbox if subscriber.email in m.to]
    assert any("United Kingdom" in m.body for m in staff_mails)
