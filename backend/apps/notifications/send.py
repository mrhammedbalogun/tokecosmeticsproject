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

from apps.notifications.branding import brand_context


def send_email(template_name: str, to, context: dict) -> None:
    if isinstance(to, str):
        to = [to]

    # Brand facts UNDER the caller's context, never over it: the shell needs the logo
    # and the social links, but a caller that deliberately passes its own `shop_url`
    # (or a test that pins one) must still win. See branding.py for why this is injected
    # here rather than at each call site.
    context = {**brand_context(), **context}

    subject = render_to_string(f"email/{template_name}.subject.txt", context).strip()
    text_body = render_to_string(f"email/{template_name}.txt", context)
    html_body = render_to_string(f"email/{template_name}.html", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=to,
        # Several templates say "just reply to this email". The From address is on the
        # Resend SENDING subdomain (mg.tokecosmetics.com), which has no inbox, so without
        # this those replies go nowhere. `EMAIL_REPLY_TO` defaults to sales@ and the
        # `if` only guards a deliberately blanked one — Django rejects `reply_to=[""]`.
        reply_to=[settings.EMAIL_REPLY_TO] if getattr(settings, "EMAIL_REPLY_TO", "") else None,
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()
