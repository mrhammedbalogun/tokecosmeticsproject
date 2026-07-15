from unittest import mock

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


def test_send_email_falls_back_to_ses():
    with mock.patch(
        "apps.notifications.send._send_via", side_effect=[RuntimeError("mailgun down"), None]
    ) as m:
        send_email("password_reset", "a@b.com", {"reset_url": "https://x/y", "first_name": "A"})
        assert m.call_count == 2  # primary failed, then SES
