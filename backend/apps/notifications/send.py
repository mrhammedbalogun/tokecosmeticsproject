"""Single email entry point.

`send_email` renders an HTML + text template and sends via the default backend
(Resend in prod, console in dev/tests). Resend is the sole provider — there is no
second provider to fall back to; transient failures are retried by the Celery task
`send_email_task` (see tasks.py).
"""
from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_email(template_name: str, to, context: dict) -> None:
    if isinstance(to, str):
        to = [to]
    subject = render_to_string(f"email/{template_name}.subject.txt", context).strip()
    text_body = render_to_string(f"email/{template_name}.txt", context)
    html_body = render_to_string(f"email/{template_name}.html", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=to,
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()
