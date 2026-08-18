"""The shell is branded, and it is branded from ONE place.

These are regression tests for the redesign, not decoration. Every one of them protects a
failure that is invisible in development and only shows up in a recipient's inbox:

* the logo and icons load from an ABSOLUTE url — a relative `src` renders as a broken
  image everywhere, and nothing in a local render would tell you;
* the socials come from `branding.SOCIAL_LINKS`, so adding a platform is one edit rather
  than twenty;
* staff and ops mail does NOT carry the shop's marketing furniture;
* the text part carries the same links, because a chunk of readers only ever see it.
"""
from __future__ import annotations

import pytest
from django.core import mail
from django.test import override_settings

from apps.notifications.branding import SOCIAL_LINKS, brand_context
from apps.notifications.send import send_email

CUSTOMER_TEMPLATES = [
    "order_delivered", "verify_email", "password_reset", "referral_payout_paid",
]
INTERNAL_TEMPLATES = ["admin_otp", "staff_invite", "recipient_confirm", "gig_wallet_low"]


def _html(msg) -> str:
    return "".join(a[0] for a in msg.alternatives)


def _send(template: str, **context) -> tuple[str, str]:
    mail.outbox.clear()
    send_email(template, "someone@example.com", context)
    msg = mail.outbox[-1]
    return _html(msg), msg.body


@override_settings(FRONTEND_URL="https://shop.example.com")
def test_the_logo_and_icons_load_from_an_absolute_url():
    """A relative `src` resolves against nothing in a mail client. There is no page for it
    to be relative TO, so it is a broken image in every inbox — and a local render, which
    has an origin, shows it working."""
    html, _ = _send("verify_email", first_name="Jo", verify_url="https://x/y")

    assert 'src="https://shop.example.com/email/logo.png"' in html
    for _label, _url, icon in SOCIAL_LINKS:
        assert f'src="https://shop.example.com/email/{icon}"' in html


@pytest.mark.parametrize("template", CUSTOMER_TEMPLATES)
def test_customer_mail_carries_every_social_account(template):
    html, text = _send(template, first_name="Jo", verify_url="https://x", reset_url="https://x",
                       amount="₦1.00", bank_name="B", account_masked="•••• 1",
                       reference="R", referrals_url="https://x", items=[], number="TC-1")

    for label, url, _icon in SOCIAL_LINKS:
        assert url in html, f"{template}: {label} missing from the HTML part"
        assert url in text, f"{template}: {label} missing from the TEXT part"
        # Alt text IS the link for the many readers whose client blocks images.
        assert f'alt="{label}"' in html


@pytest.mark.parametrize("template", INTERNAL_TEMPLATES)
def test_internal_mail_carries_no_shop_furniture(template):
    """Staff and ops alerts are not marketing. A "follow us on TikTok" row under a
    low-stock alert is noise for the person it is addressed to, and a "Shop" link points
    them at the wrong application entirely."""
    html, _ = _send(template, first_name="Jo", code="123456", expires_minutes=10,
                    invited_by="Owner", role="Fulfilment", expires_hours=48,
                    invite_url="https://x", address="a@b.c", event_label="New paid order",
                    event_description="d", confirm_url="https://x",
                    balance="1,000.00", threshold="50,000")

    for _label, url, _icon in SOCIAL_LINKS:
        assert url not in html
    assert ">Shop</a>" not in html
    assert "Open the admin" in html


def test_the_brand_context_never_overrides_the_caller():
    """`send_email` merges the brand facts UNDER the caller's context. A caller that
    passes its own `shop_url` — or a test that pins one — has to win, or the merge would
    silently rewrite live values."""
    html, _ = _send("verify_email", first_name="Jo", verify_url="https://x",
                    brand_name="Something Else")

    assert "Something Else" in html


def test_urls_have_no_double_slash_when_settings_carry_a_trailing_one():
    with override_settings(FRONTEND_URL="https://shop.example.com/"):
        context = brand_context()

    assert context["logo_url"] == "https://shop.example.com/email/logo.png"
    assert context["shop_url"] == "https://shop.example.com"


def test_every_mail_is_replyable():
    """Five customer templates say "just reply to this email". The From address is a
    Resend sending subdomain with no inbox, so without a Reply-To that sentence is a lie
    the customer only discovers after writing the reply."""
    mail.outbox.clear()
    send_email("order_delivered", "buyer@example.com", {"items": [], "number": "TC-1"})

    assert mail.outbox[-1].reply_to == ["sales@tokecosmetics.com"]


def test_the_footer_prints_the_address_replies_go_to():
    """One inbox, reached two ways. A footer contact link pointing somewhere other than
    the reply button is how a customer ends up in the mailbox nobody watches."""
    html, text = _send("order_delivered", items=[], number="TC-1")

    assert "mailto:sales@tokecosmetics.com" in html
    # And in the text part, where there is no mailto to click.
    assert "sales@tokecosmetics.com" in text


@override_settings(EMAIL_REPLY_TO="")
def test_a_blanked_reply_to_sends_none_rather_than_an_empty_address():
    """Django rejects `reply_to=[""]`, so the setting has to collapse to None, not to a
    list holding an empty string."""
    mail.outbox.clear()
    send_email("order_delivered", "buyer@example.com", {"items": [], "number": "TC-1"})

    assert mail.outbox[-1].reply_to == []
