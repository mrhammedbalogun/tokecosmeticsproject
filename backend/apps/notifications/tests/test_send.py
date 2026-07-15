from unittest import mock

import pytest
from django.core import mail

from apps.notifications.send import send_email


def test_send_email_renders_and_sends(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []
    send_email("password_reset", "a@b.com", {"reset_url": "https://x/y", "first_name": "A"})
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert "a@b.com" in msg.to
    assert "Reset your Toke Cosmetics password" in msg.subject
    assert "https://x/y" in msg.body


def test_send_email_from_uses_verified_domain(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []
    send_email("password_reset", "a@b.com", {"reset_url": "https://x/y", "first_name": "A"})
    # Resend only accepts mail from the verified sending domain.
    assert "mg.tokecosmetics.com" in mail.outbox[0].from_email


def test_send_email_propagates_errors():
    # No provider fallback: a send failure must bubble up so send_email_task can retry.
    with mock.patch(
        "apps.notifications.send.EmailMultiAlternatives.send",
        side_effect=RuntimeError("resend down"),
    ):
        with pytest.raises(RuntimeError):
            send_email("password_reset", "a@b.com", {"reset_url": "https://x/y", "first_name": "A"})
