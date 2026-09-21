"""The two mails an application sends, and the rule about what may be in them.

The STAFF alert is in the notifications registry, so `test_every_event_template_renders`
already proves its three files exist and render. What it cannot prove is the thing that
matters here — that the alert carries no contact details and no CV — because that is a
property of the CONTENT, not of the template loading.

The APPLICANT's confirmation is not in the registry at all (nobody subscribes to it; it
goes to the person who applied), so nothing else renders it. Without this file a typo in
it would first be discovered by a candidate.
"""
import pytest
from django.template.loader import render_to_string

from apps.careers.emails import notify_application_received
from apps.careers.factories import posting
from apps.careers.models import JobApplication
from apps.notifications.branding import brand_context
from apps.notifications.preview import preview_context

pytestmark = pytest.mark.django_db

STAFF = "careers_application_received"
APPLICANT = "careers_application_received_applicant"


def render(stem: str, context: dict) -> tuple[str, str, str]:
    merged = {**brand_context(), **context}
    return (
        render_to_string(f"email/{stem}.subject.txt", merged).strip(),
        render_to_string(f"email/{stem}.txt", merged),
        render_to_string(f"email/{stem}.html", merged),
    )


def test_the_staff_alert_names_the_role_and_the_candidate(): 
    subject, text, html = render(STAFF, preview_context("careers.application_received"))
    assert "Sales Representative" in subject
    for body in (text, html):
        assert "Ada Obi" in body
        assert "Sales Representative" in body


def test_THE_STAFF_ALERT_CARRIES_NO_CONTACT_DETAILS_AND_NO_CV():
    """THE PROPERTY. An external address on the recipient list has no login and no second
    factor behind it — by design, that is what "external" means on that screen. If this
    mail ever grows an email address, a phone number or a link to a CV, every subscriber
    gets a copy of the most sensitive record in the system, outside every control built
    for it."""
    context = {
        **preview_context("careers.application_received"),
        # Values that WOULD appear if somebody widened the context carelessly.
        "email": "ada@example.com",
        "phone": "+2348023900964",
        "cover_letter": "Why I want to leave my current employer.",
        "resume_key": "recruitment/resumes/deadbeef.pdf",
    }
    _, text, html = render(STAFF, context)
    for body in (text, html):
        for forbidden in ("ada@example.com", "+2348023900964", "recruitment/",
                          "leave my current employer"):
            assert forbidden not in body, f"the staff alert leaked {forbidden!r}"


def test_the_applicant_confirmation_renders_and_promises_no_deadline():
    """No "we will respond within X days". One person reads these, and a deadline in an
    automated mail is a complaint waiting to arrive."""
    subject, text, html = render(APPLICANT, {
        "candidate_name": "Ada",
        "job_title": "Sales Representative",
        "location_label": "Enugu",
        "careers_url": "https://tokecosmetics.com/careers",
    })
    assert "received your application" in subject.lower()
    for body in (text, html):
        assert "Sales Representative" in body
        assert "Hi Ada" in body
    for body in (text, html):
        for promise in ("within", "business days", "48 hours", "working days"):
            assert promise not in body.lower()


def test_the_applicant_confirmation_survives_a_one_word_name():
    """`candidate_name` is a first name split off a free-text field, so a blank is normal.
    The greeting must close up around it rather than printing "Hi ,"."""
    _, text, html = render(APPLICANT, {
        "candidate_name": "",
        "job_title": "Sales Representative",
        "location_label": "",
        "careers_url": "https://tokecosmetics.com/careers",
    })
    for body in (text, html):
        assert "Hi ," not in body
        assert "Thanks for applying" in body


def test_notifying_never_raises_even_when_the_application_is_gone():
    """It runs from a post-commit hook. An application that exists with nobody told is
    recoverable — the admin list still shows it; a 500 after the person closed the tab
    is not."""
    notify_application_received(999999)  # no row, no exception


def test_notifying_never_raises_when_the_broker_is_down(monkeypatch):
    job = posting()
    application = JobApplication.objects.create(
        job=job, job_title=job.title, full_name="Ada Obi", email="ada@example.com",
        phone="+2348023900964", resume_key="recruitment/resumes/x.pdf",
    )

    def boom(*args, **kwargs):
        raise RuntimeError("redis is down")

    monkeypatch.setattr("apps.careers.emails.notify_staff", boom)
    monkeypatch.setattr("apps.careers.emails.send_email_task.delay", boom)
    notify_application_received(application.pk)  # logged, not raised
