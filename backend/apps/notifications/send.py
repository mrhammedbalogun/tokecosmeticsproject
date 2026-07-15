"""Single email entry point.

`send_email` renders an HTML + text template and sends via the default backend
(Mailgun in prod). On an Anymail API error it retries once via Amazon SES so a
Mailgun outage doesn't drop transactional mail.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

SES_BACKEND = "anymail.backends.amazon_ses.EmailBackend"


def _send_via(connection, subject: str, text_body: str, html_body: str, to: list[str]) -> None:
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=to,
        connection=connection,
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()


def send_email(template_name: str, to, context: dict) -> None:
    if isinstance(to, str):
        to = [to]
    subject = render_to_string(f"email/{template_name}.subject.txt", context).strip()
    text_body = render_to_string(f"email/{template_name}.txt", context)
    html_body = render_to_string(f"email/{template_name}.html", context)

    try:
        _send_via(None, subject, text_body, html_body, to)  # None = default backend
    except Exception as exc:  # noqa: BLE001 — fall back to SES on any send error
        # Anymail raises AnymailAPIError; catch broadly so a Mailgun hiccup falls back.
        logger.warning("Primary email backend failed (%s); retrying via SES", exc)
        ses = get_connection(SES_BACKEND)
        _send_via(ses, subject, text_body, html_body, to)
