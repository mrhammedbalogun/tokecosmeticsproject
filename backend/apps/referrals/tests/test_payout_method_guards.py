"""The payout-method write path: capped, and noisy on ADD as well as CHANGE.

Two gaps the 2026-08-15 review found, pinned here before they were fixed:

* The PUT had no per-endpoint throttle, and every change sends the security email —
  so an authenticated caller alternating two account numbers could pump the global
  user allowance (120/min) of transactional mail through Resend from the shop's own
  domain. Given this project's deliverability history, that is a self-inflicted
  blacklisting lever; it also lets an attacker bury the one real "details changed"
  alert in hundreds of identical ones.

* The FIRST save was silent by design ("nothing to warn about yet") — but the first
  save is exactly the account-takeover window: a victim with accrued earnings and no
  method on file got no email when a hijacker added one, and the first mail they ever
  received was "you've been paid". The add email closes that.

Tests run against the REAL configured rates, same stance as
test_password_reset_throttle.py: a pinned fake rate would restate itself rather than
check the protection bites.
"""
from __future__ import annotations

import pytest
from django.core import mail
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.referrals.tests.factories import customer

METHODS = "/api/v1/me/referrals/payout-methods/"
LOOKUP = "/api/v1/referrals/lookup/"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Throttle counters live in the cache and would otherwise leak between tests."""
    cache.clear()
    yield
    cache.clear()


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _body(number="0123456789"):
    return {
        "currency": "NGN",
        "bank_name": "GTBank",
        "account_name": "Amina Adeyemi",
        "account_number": number,
    }


def test_hammering_the_payout_method_write_is_throttled(django_user_model):
    """The write is capped well below the global user allowance (120/min): each change
    is an outbound security email, so the cap is an email-volume cap."""
    user = customer(django_user_model, "amina@x.com")
    client = _client(user)

    codes = [client.put(METHODS, _body(), format="json").status_code for _ in range(7)]

    assert codes.count(429) >= 1, codes


def test_reading_payout_methods_is_not_capped_by_the_write_throttle(django_user_model):
    """The account page renders the method list on every visit; a referrer who just
    hit the write cap must still be able to SEE their details."""
    user = customer(django_user_model, "amina@x.com")
    client = _client(user)

    codes = [client.put(METHODS, _body(), format="json").status_code for _ in range(7)]
    assert 429 in codes, "precondition: the write cap tripped"

    assert client.get(METHODS).status_code == 200


def test_the_first_payout_method_save_emails_the_account_holder(
    django_user_model, django_capture_on_commit_callbacks
):
    """The ADD is the account-takeover window, not just the change: a victim with
    earnings and no method on file must hear about a bank account appearing."""
    user = customer(django_user_model, "amina@x.com", first_name="Amina")
    client = _client(user)

    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        r = client.put(METHODS, _body(), format="json")

    assert r.status_code == 200
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "added" in body.lower()
    # Masked tail only — an inbox is the least controlled place the shop writes to.
    assert "•••• 6789" in body
    assert "0123456789" not in body


def test_a_change_still_emails_and_says_changed_not_added(
    django_user_model, django_capture_on_commit_callbacks
):
    user = customer(django_user_model, "amina@x.com", first_name="Amina")
    client = _client(user)

    with django_capture_on_commit_callbacks(execute=True):
        client.put(METHODS, _body("0123456789"), format="json")
    mail.outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        r = client.put(METHODS, _body("9876543210"), format="json")

    assert r.status_code == 200
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "changed" in body.lower()
    assert "•••• 3210" in body
    assert "9876543210" not in body


def test_a_no_op_resave_sends_nothing(django_user_model, django_capture_on_commit_callbacks):
    """Submitting the form unchanged is not an event anybody needs to hear about —
    and 'no change, no email' is what keeps the real alerts meaningful."""
    user = customer(django_user_model, "amina@x.com")
    client = _client(user)

    with django_capture_on_commit_callbacks(execute=True):
        client.put(METHODS, _body(), format="json")
    mail.outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        r = client.put(METHODS, _body(), format="json")

    assert r.status_code == 200
    assert mail.outbox == []


def test_account_number_refuses_exotic_characters(django_user_model):
    """The number is published UNMASKED on the admin payout queue — the screen staff
    copy into a banking app — so RTL overrides, zero-width junk and lookalike digits
    must not be storable. Spaces and hyphens still normalise away; plain alphanumerics
    (IBANs included) still pass."""
    user = customer(django_user_model, "amina@x.com")
    client = _client(user)

    for bad in ("01234‮56789", "０１２３４５６７８９", "01234 6789​"):
        r = client.put(METHODS, _body(bad), format="json")
        assert r.status_code == 400, bad

    assert client.put(METHODS, _body("GB29 NWBK-6016-1331926819"), format="json").status_code == 200


def test_the_public_lookup_throttle_actually_bites():
    """Pinned so a future edit dropping `throttle_classes` from the lookup view is a
    test failure rather than a silent unmetered enumeration surface (60/min)."""
    anon = APIClient()
    codes = [anon.get(LOOKUP, {"code": f"PROBE{i:04d}"}).status_code for i in range(61)]
    assert codes.count(429) >= 1


def test_the_plain_text_email_renders_ampersands_and_apostrophes_verbatim(
    django_user_model, django_capture_on_commit_callbacks
):
    """Django autoescapes .txt templates too unless told not to — so "M&T Bank"
    arrived as "M&amp;amp;T Bank" in the plain-text part. HTML parts keep escaping."""
    user = customer(django_user_model, "amina@x.com")
    client = _client(user)

    body = _body()
    body["bank_name"] = "M&T Bank"
    body["account_name"] = "Amina O'Brien"
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        client.put(METHODS, body, format="json")

    text = mail.outbox[0].body
    assert "M&T Bank" in text
    assert "Amina O'Brien" in text
    assert "&amp;" not in text and "&#x27;" not in text
