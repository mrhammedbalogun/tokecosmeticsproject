"""The two emails an application produces, and the rule about what may be in them.

── THE STAFF ALERT CARRIES NO CONTACT DETAILS ──────────────────────────────────

Only who applied, where they study, and a link into the admin. The same rule the careers
alert follows (`apps/careers/emails.py`), and it matters here for the same reason: an
external address on the recipient list — a shared programme@ inbox, a coordinator who is
not staff — is BY DESIGN an address with no admin login and no second factor. Putting a
student's email and phone number in a mail to it would hand every subscriber a copy of
the record, outside every control built for it.

So the mail names the student and their institution and says "open the admin". Reading
the rest is an authenticated, scoped, audited act, which is the whole point.

`apps/entrepreneurship/tests/test_emails.py` is what keeps that true, and it is the
reason `entrepreneurship.notifications.manage` can sit at {Owner, Manager} rather than
at the Owner-only `settings.manage` that guards the same table for every other event.

── THE APPLICANT'S CONFIRMATION EXISTS BECAUSE SILENCE IS THE OLD BEHAVIOUR ────

The WordPress form said "Your message has been sent" on a page and then nothing ever
again. A one-line acknowledgement is the smallest honest improvement, and it doubles as
the proof-of-delivery that tells US the address they typed is real — which matters more
here than on a careers form, because this address is how we reach somebody we are about
to hand stock to.
"""
from __future__ import annotations

import logging

from django.conf import settings

from apps.notifications.staff import notify_staff
from apps.notifications.tasks import send_email_task

logger = logging.getLogger(__name__)

EVENT_APPLICATION_RECEIVED = "entrepreneurship.application_received"


def notify_application_received(application_id: int) -> None:
    """Fan out both mails for one application. NEVER raises.

    Takes an ID rather than an instance and re-reads the row, so it is safe to call from
    a post-commit hook and from a Celery task alike; and if the row is gone by then
    (deleted in the seconds after it was written), it is a no-op rather than a traceback.

    FAILURE IS NOT THE APPLICANT'S PROBLEM. An application that exists with nobody told
    is recoverable — the admin list still shows it. An application rolled back because
    the broker blinked is not, and the student has already closed the tab.
    """
    from apps.entrepreneurship.models import ProgramApplication

    application = (
        ProgramApplication.objects.select_related("country")
        .filter(pk=application_id)
        .first()
    )
    if application is None:
        return

    admin_url = (
        f"{settings.ADMIN_URL.rstrip('/')}/entrepreneurship/{application.pk}"
    )
    try:
        notify_staff(
            EVENT_APPLICATION_RECEIVED,
            {
                "student_name": application.full_name,
                "institution": application.institution,
                "academic_level": application.academic_level,
                "course_of_study": application.course_of_study,
                "country_name": application.country.name,
                "has_motivation": bool(application.motivation),
                "is_resubmission": application.is_resubmission
                or application.submission_count > 1,
                "application_url": admin_url,
            },
        )
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception(
            "entrepreneurship: staff alert failed for application %s", application_id
        )

    try:
        send_email_task.delay(
            "programme_application_received_applicant",
            application.email,
            {
                # First name only. `full_name` is one free-text field, so the split is a
                # heuristic — which is why the templates treat a blank as normal and
                # close the sentence up around it rather than printing "Hi ,".
                "student_name": application.full_name.split(" ")[0].strip(),
                "institution": application.institution,
                # Not in `brand_context` — only this mail needs it, and adding it there
                # would put a programme link in the footer of every order confirmation.
                "programme_url": (
                    f"{settings.FRONTEND_URL.rstrip('/')}/entrepreneurial-program"
                ),
            },
        )
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception(
            "entrepreneurship: applicant confirmation failed for application %s",
            application_id,
        )
