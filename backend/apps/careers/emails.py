"""The two emails an application produces, and the rule about what may be in them.

── THE STAFF ALERT CARRIES NO CV AND NO COVER LETTER ───────────────────────────

Only who applied, for what, and a link into the admin. The same rule the staff order
alert already follows (`apps/orders/emails.py::_staff_context` deliberately omits the
customer's phone and street address), and here it matters more: an external address on
the recipient list — a bookkeeper, a shared careers@ inbox — is by design an address
with no admin login and no second factor behind it. Putting a stranger's CV, phone
number and employment history in a mail to it would hand every subscriber a copy of the
most sensitive record this system holds, outside every control built for it.

So the mail names the role and the candidate and says "open the admin". Reading the
application is an authenticated, scoped, audited act, which is the whole point.

── THE APPLICANT'S CONFIRMATION EXISTS BECAUSE SILENCE IS THE OLD BEHAVIOUR ────

The WordPress page told people to email careers@ and told them nothing after that. A
one-line acknowledgement is the smallest honest improvement, and it doubles as the
proof-of-delivery that tells US the address they typed is real.
"""
from __future__ import annotations

import logging

from django.conf import settings

from apps.notifications.staff import notify_staff
from apps.notifications.tasks import send_email_task

logger = logging.getLogger(__name__)

EVENT_APPLICATION_RECEIVED = "careers.application_received"


def notify_application_received(application_id: int) -> None:
    """Fan out both mails for one application. NEVER raises.

    Takes an ID rather than an instance and re-reads the row, so it is safe to call from
    a post-commit hook and from a Celery task alike; and if the row is gone by then
    (deleted in the seconds after it was written), it is a no-op rather than a traceback.

    FAILURE IS NOT THE APPLICANT'S PROBLEM. An application that exists with nobody told
    is recoverable — the admin list still shows it. An application rolled back because
    the broker blinked is not, and the person has already closed the tab.
    """
    from apps.careers.models import JobApplication

    application = (
        JobApplication.objects.select_related("job").filter(pk=application_id).first()
    )
    if application is None:
        return

    admin_url = f"{settings.ADMIN_URL.rstrip('/')}/careers/applications/{application.pk}"
    try:
        notify_staff(
            EVENT_APPLICATION_RECEIVED,
            {
                "candidate_name": application.full_name,
                "job_title": application.job_title,
                "location_label": application.location_label,
                "has_cover_letter": bool(application.cover_letter),
                "is_resubmission": application.is_resubmission
                or application.submission_count > 1,
                "application_url": admin_url,
            },
        )
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception("careers: staff alert failed for application %s", application_id)

    try:
        send_email_task.delay(
            "careers_application_received_applicant",
            application.email,
            {
                # First name only. `full_name` is one free-text field, so the split is a
                # heuristic — which is why the templates treat a blank as normal and
                # close the sentence up around it rather than printing "Hi ,".
                "candidate_name": application.full_name.split(" ")[0].strip(),
                "job_title": application.job_title,
                "location_label": application.location_label,
                # Not in `brand_context` — only this mail needs it, and adding it there
                # would put a careers link in the footer of every order confirmation.
                "careers_url": f"{settings.FRONTEND_URL.rstrip('/')}/careers",
            },
        )
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception(
            "careers: applicant confirmation failed for application %s", application_id
        )
