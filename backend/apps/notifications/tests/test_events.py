"""The seatbelts that keep the registry, the templates and the previews in step.

Every failure in this file is a bug that would otherwise appear in production as an
alert that does not arrive, or a 500 inside a Celery worker at the exact moment
something has already gone wrong in the shop. That is the worst possible time to learn
about a missing template, which is why these are asserted here instead.
"""
import pytest
from django.core import mail
from django.template.loader import render_to_string

from apps.notifications.events import EVENTS, EVENTS_BY_CODE
from apps.notifications.preview import _PREVIEWS, preview_context
from apps.notifications.send import send_email


@pytest.fixture(autouse=True)
def _locmem(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


def test_event_codes_are_unique():
    codes = [event.code for event in EVENTS]
    assert len(codes) == len(set(codes))


def test_every_event_has_a_preview_context():
    """A missing preview is a 500 the first time somebody presses "Send test"."""
    assert set(_PREVIEWS) == set(EVENTS_BY_CODE)


@pytest.mark.parametrize("event", EVENTS, ids=[e.code for e in EVENTS])
def test_every_event_template_renders(event):
    """All three files, against the event's own sample context.

    A template that renders only under a mock is a template that breaks in production —
    the same reasoning `apps/orders/tests/test_emails.py` opens with.
    """
    context = preview_context(event.code)
    subject = render_to_string(f"email/{event.template}.subject.txt", context).strip()
    text = render_to_string(f"email/{event.template}.txt", context)
    html = render_to_string(f"email/{event.template}.html", context)

    assert subject, f"{event.template} rendered an empty subject"
    assert text.strip()
    assert html.strip()


@pytest.mark.parametrize("event", EVENTS, ids=[e.code for e in EVENTS])
def test_every_event_survives_send_email(event):
    """The registry's template name is the one `send_email` is actually handed. A stem
    that renders under `render_to_string` but is misspelled in the registry entry would
    pass the test above and fail here."""
    send_email(event.template, "someone@example.com", preview_context(event.code))
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["someone@example.com"]


def test_preview_context_is_json_serialisable():
    """Every context crosses Celery, which is configured for JSON
    (`CELERY_TASK_SERIALIZER`). A Decimal in here is a task that dies on the queue."""
    import json

    for code in EVENTS_BY_CODE:
        json.dumps(preview_context(code))


def test_preview_context_returns_a_copy():
    first = preview_context("order.paid")
    first["number"] = "MUTATED"
    assert preview_context("order.paid")["number"] == "TC-000000"


def test_unregistered_event_has_no_preview():
    assert preview_context("nope.nope") == {}
