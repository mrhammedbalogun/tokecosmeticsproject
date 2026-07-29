"""Staff invites — the only way a new administrator comes into existence.

WHAT IS BEING PROTECTED. An outstanding invite is a live staff-creation capability:
whoever holds the token can mint an `is_staff` account in a named role. Every test
here exists because some way of holding that capability longer, or using it twice, or
using it without holding it, would be a way of becoming an administrator.

The load-bearing properties, each with a test that fails loudly:

1. **Single-use, and race-proof.** The claim is ONE atomic conditional UPDATE, not a
   check followed by a set. `test_two_concurrent_accepts_yield_exactly_one_staff_account`
   drives it from two real connections rather than asserting the happy path.
2. **Time-bounded and revocable.** Expired, revoked and already-used invites all fail.
   Revocation is the kill switch for a mis-sent invite; without it a typo in an address
   means waiting out the whole TTL with no recourse.
3. **The accept endpoint cannot be used to lock out the new hire.** Its throttle bucket
   is touched only by *invalid* tokens — see the docstrings on
   `test_a_valid_accept_touches_no_throttle_bucket` and its twin.
4. **Accepting does not produce an admin session.** It returns a PREAUTH token, which
   opens nothing at all until Task 3b builds TOTP enrolment.
5. **Promotion never inherits a customer-era password.** The accept flow always sets a
   new one.
"""
import hashlib
import logging
import re
import threading

import httpx
import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.db import connection, connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PW = "Str0ng!pass9"
NEW_PW = "An0ther!pass7"

INVITES = "/api/v1/admin/staff/invites/"
ACCEPT = "/api/v1/admin/staff/invites/accept/"
ADMIN_ME = "/api/v1/auth/admin-me/"
CUSTOMER_TOKEN = "/api/v1/auth/token/"


def revoke_url(invite_id) -> str:
    return f"{INVITES}{invite_id}/revoke/"


# --- fixtures -----------------------------------------------------------------


@pytest.fixture
def owner(django_user_model):
    user = django_user_model.objects.create_user(
        email="owner@toke.test", password=PW, is_staff=True, first_name="Toke", last_name="Owner"
    )
    user.groups.add(Group.objects.get(name="Owner"))
    return user


@pytest.fixture
def manager(django_user_model):
    user = django_user_model.objects.create_user(
        email="manager@toke.test", password=PW, is_staff=True
    )
    user.groups.add(Group.objects.get(name="Manager"))
    return user


@pytest.fixture
def owner_client(owner):
    client = APIClient()
    client.force_authenticate(owner)
    return client


@pytest.fixture
def mailbox(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []
    return mail.outbox


def token_from_mail(message) -> str:
    """The raw token out of the invite link. The only place it ever exists after the
    response to the create call — by design, since nothing but the mail carries it."""
    match = re.search(r"accept-invite\?token=([A-Za-z0-9_-]+)", message.body)
    assert match, f"no invite link in the mail body:\n{message.body}"
    return match.group(1)


def invite_for(owner_client, mailbox, email="newhire@toke.test", role="Support"):
    """Create an invite over HTTP and return `(response, raw_token)`."""
    response = owner_client.post(INVITES, {"email": email, "role": role}, format="json")
    assert response.status_code == 201, response.data
    return response, token_from_mail(mailbox[-1])


class _Recorder:
    def __init__(self, response):
        self.calls = []
        self.response = response

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def _siteverify(monkeypatch, *, success=True):
    from apps.accounts.turnstile import SITEVERIFY_URL

    response = httpx.Response(
        200, request=httpx.Request("POST", SITEVERIFY_URL), json={"success": success}
    )
    recorder = _Recorder(response)
    monkeypatch.setattr("apps.accounts.turnstile.httpx.post", recorder)
    return recorder


def _security_records(caplog, level):
    return [
        rec
        for rec in caplog.records
        if rec.name == "apps.security" and rec.levelno == level
    ]


# --- create -------------------------------------------------------------------


def test_owner_creates_an_invite(owner_client, mailbox):
    response, _token = invite_for(owner_client, mailbox)
    from apps.accounts.models import StaffInvite

    invite = StaffInvite.objects.get()
    assert invite.email == "newhire@toke.test"
    assert invite.role.name == "Support"
    assert invite.accepted_at is None and invite.revoked_at is None
    assert response.data["email"] == "newhire@toke.test"
    assert response.data["role"] == "Support"


def test_the_stored_token_is_a_hash_and_the_raw_token_is_never_returned(owner_client, mailbox):
    """The database holds a digest, so a database read — a backup, a dump, a SQL
    injection elsewhere — does not hand anybody a staff-creation capability."""
    from apps.accounts.models import StaffInvite

    response, raw = invite_for(owner_client, mailbox)
    invite = StaffInvite.objects.get()

    assert invite.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in str(response.data), "the create response leaked the raw token"
    assert raw != invite.token_hash


def test_the_invite_mail_links_to_the_admin_app(owner_client, mailbox, settings):
    _response, raw = invite_for(owner_client, mailbox)
    message = mailbox[-1]
    assert message.to == ["newhire@toke.test"]
    assert f"{settings.ADMIN_URL}/accept-invite?token={raw}" in message.body


def test_the_invite_expires_in_the_configured_window(owner_client, mailbox, settings):
    from apps.accounts.models import StaffInvite

    invite_for(owner_client, mailbox)
    invite = StaffInvite.objects.get()
    hours = (invite.expires_at - timezone.now()).total_seconds() / 3600
    assert settings.STAFF_INVITE_TTL_HOURS - 1 < hours <= settings.STAFF_INVITE_TTL_HOURS


def test_a_non_owner_staff_member_cannot_invite(manager):
    """`staff.manage` is Owner-only: inviting staff mints administrators, so it is one
    of the two scopes that can escalate privilege."""
    client = APIClient()
    client.force_authenticate(manager)
    r = client.post(INVITES, {"email": "x@toke.test", "role": "Support"}, format="json")
    assert r.status_code == 403


def test_an_anonymous_caller_cannot_invite():
    r = APIClient().post(INVITES, {"email": "x@toke.test", "role": "Support"}, format="json")
    assert r.status_code == 401


def test_inviting_an_existing_staff_member_is_refused(owner_client, django_user_model, mailbox):
    """An invite whose meaning is sometimes-create and sometimes-modify-existing-staff
    is how an audit trail rots: "how did this person become a Manager?" stops having
    one answer. Changing an existing staff member's role is a group edit, not an invite.
    """
    django_user_model.objects.create_user(
        email="already@toke.test", password=PW, is_staff=True
    )
    r = owner_client.post(
        INVITES, {"email": "already@toke.test", "role": "Manager"}, format="json"
    )
    assert r.status_code == 400
    assert "groups" in str(r.data).lower()
    assert mailbox == [], "a refused invite still sent mail"


def test_a_second_outstanding_invite_for_the_same_address_is_refused(owner_client, mailbox):
    """Two live tokens for one address means the older one survives the "resend" that
    was meant to replace it — and an accepted invite always sets a password, so a stale
    token is a silent staff-password reset sitting in an old inbox. Resend is revoke +
    invite, and this is what makes that the only way to do it."""
    invite_for(owner_client, mailbox)
    r = owner_client.post(
        INVITES, {"email": "newhire@toke.test", "role": "Support"}, format="json"
    )
    assert r.status_code == 400
    assert "revoke" in str(r.data).lower()


def test_a_revoked_invite_does_not_block_a_fresh_one(owner_client, mailbox):
    response, _raw = invite_for(owner_client, mailbox)
    assert owner_client.post(revoke_url(response.data["id"])).status_code == 200
    again = owner_client.post(
        INVITES, {"email": "newhire@toke.test", "role": "Support"}, format="json"
    )
    assert again.status_code == 201


def test_an_unknown_role_is_refused(owner_client, mailbox):
    r = owner_client.post(
        INVITES, {"email": "x@toke.test", "role": "Superuser"}, format="json"
    )
    assert r.status_code == 400
    assert mailbox == []


def test_a_malformed_address_is_refused(owner_client, mailbox):
    r = owner_client.post(
        INVITES, {"email": "not-an-email", "role": "Support"}, format="json"
    )
    assert r.status_code == 400
    assert mailbox == []


def test_creating_an_invite_records_who_invited_whom(owner_client, owner, mailbox, caplog):
    """`invited_by` is only half the provenance trail — it says who, but it lives on a
    row that can be deleted. The log line is the half that survives."""
    from apps.accounts.models import StaffInvite

    with caplog.at_level(logging.INFO, logger="apps.security"):
        invite_for(owner_client, mailbox)

    assert StaffInvite.objects.get().invited_by == owner
    lines = [rec.getMessage() for rec in _security_records(caplog, logging.INFO)]
    assert any(
        "staff invite created" in line
        and "newhire@toke.test" in line
        and "Support" in line
        and owner.email in line
        for line in lines
    ), lines


def test_the_raw_token_never_reaches_the_security_log(owner_client, mailbox, caplog):
    """The link in the recipient's mailbox (and in Resend's stored copy) is the same
    accepted exposure password reset already carries. A log line is not — logs are read
    by more people, shipped to Sentry, and kept longer."""
    with caplog.at_level(logging.INFO):
        _response, raw = invite_for(owner_client, mailbox)
    assert not any(raw in rec.getMessage() for rec in caplog.records)


# --- revoke -------------------------------------------------------------------


def test_owner_revokes_an_outstanding_invite(owner_client, mailbox, caplog):
    from apps.accounts.models import StaffInvite

    response, _raw = invite_for(owner_client, mailbox)
    with caplog.at_level(logging.INFO, logger="apps.security"):
        r = owner_client.post(revoke_url(response.data["id"]))
    assert r.status_code == 200
    assert StaffInvite.objects.get().revoked_at is not None
    assert any(
        "staff invite revoked" in rec.getMessage()
        for rec in _security_records(caplog, logging.INFO)
    )


def test_revoking_twice_is_idempotent(owner_client, mailbox):
    """An operator who mis-sent an invite will hit the button twice. The state that
    matters (revoked) is already true, so a second call is a success, not an error."""
    response, _raw = invite_for(owner_client, mailbox)
    assert owner_client.post(revoke_url(response.data["id"])).status_code == 200
    assert owner_client.post(revoke_url(response.data["id"])).status_code == 200


def test_an_accepted_invite_cannot_be_revoked(owner_client, mailbox):
    """Revocation is a kill switch for an UNUSED capability. Once the account exists,
    deleting the invite row would not un-make it — the honest action is to demote the
    staff member, and pretending otherwise would let an operator think they had."""
    response, raw = invite_for(owner_client, mailbox)
    assert APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json").status_code == 200
    r = owner_client.post(revoke_url(response.data["id"]))
    assert r.status_code == 400


def test_a_non_owner_cannot_revoke(owner_client, mailbox, manager):
    response, _raw = invite_for(owner_client, mailbox)
    client = APIClient()
    client.force_authenticate(manager)
    assert client.post(revoke_url(response.data["id"])).status_code == 403


def test_an_anonymous_caller_cannot_revoke(owner_client, mailbox):
    response, _raw = invite_for(owner_client, mailbox)
    assert APIClient().post(revoke_url(response.data["id"])).status_code == 401


def test_owner_can_list_outstanding_invites_without_seeing_tokens(owner_client, mailbox):
    """Revocation needs an id, so the list is what makes the kill switch reachable."""
    _response, raw = invite_for(owner_client, mailbox)
    r = owner_client.get(INVITES)
    assert r.status_code == 200
    body = str(r.data)
    assert "newhire@toke.test" in body
    assert raw not in body


# --- accept: the happy path ---------------------------------------------------


def test_accepting_creates_a_staff_account_in_the_invited_role(
    owner_client, mailbox, django_user_model
):
    _response, raw = invite_for(owner_client, mailbox, role="Support")
    r = APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    assert r.status_code == 200, r.data

    user = django_user_model.objects.get(email="newhire@toke.test")
    assert user.is_staff is True
    assert list(user.groups.values_list("name", flat=True)) == ["Support"]
    assert user.check_password(NEW_PW)


def test_accepting_marks_the_invite_used(owner_client, mailbox):
    from apps.accounts.models import StaffInvite

    _response, raw = invite_for(owner_client, mailbox)
    APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    assert StaffInvite.objects.get().accepted_at is not None


def test_accepting_logs_the_new_administrator(owner_client, mailbox, caplog):
    with caplog.at_level(logging.INFO, logger="apps.security"):
        _response, raw = invite_for(owner_client, mailbox)
        APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    assert any(
        "staff invite accepted" in rec.getMessage() and "newhire@toke.test" in rec.getMessage()
        for rec in _security_records(caplog, logging.WARNING)
    )


# --- accept: what the returned token is, and is not ---------------------------


def test_accepting_returns_a_preauth_token_and_no_refresh(owner_client, mailbox):
    from apps.accounts.authentication import (
        ADMIN_AUDIENCE_CLAIM,
        ADMIN_PREAUTH_AUDIENCE,
    )
    from rest_framework_simplejwt.tokens import AccessToken

    _response, raw = invite_for(owner_client, mailbox)
    r = APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")

    assert "refresh" not in r.data and "access" not in r.data
    assert AccessToken(r.data["preauth_token"])[ADMIN_AUDIENCE_CLAIM] == ADMIN_PREAUTH_AUDIENCE


def test_the_preauth_token_opens_only_the_totp_ceremony(owner_client, mailbox):
    """Amendment 6's invariant has no bootstrap exception: the admin audience claim
    means password + Turnstile + TOTP, and accepting an invite proves only the first
    two. So a freshly accepted invite produces an account that is real, is_staff, in its
    group — and reaches nothing but the enrolment it owes.

    The exact three-endpoint set is asserted in `test_staff_totp.py`; what this file
    cares about is that the token accept-invite hands out is on the same footing as the
    one the login hands out, i.e. that there is ONE bootstrap path and not two."""
    _response, raw = invite_for(owner_client, mailbox)
    preauth = APIClient().post(
        ACCEPT, {"token": raw, "password": NEW_PW}, format="json"
    ).data["preauth_token"]

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {preauth}")
    assert client.get(ADMIN_ME).status_code == 401
    assert client.get("/api/v1/admin/orders/").status_code == 401
    assert client.get("/api/v1/auth/me/").status_code == 401

    # ...but it does open enrolment, which is the whole point of handing it out.
    assert client.post("/api/v1/auth/admin-totp/enrol/", {}, format="json").status_code == 200


def test_the_preauth_token_is_short_lived(owner_client, mailbox):
    from datetime import UTC, datetime

    from rest_framework_simplejwt.tokens import AccessToken

    from apps.accounts.authentication import PREAUTH_TOKEN_LIFETIME

    _response, raw = invite_for(owner_client, mailbox)
    r = APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    token = AccessToken(r.data["preauth_token"])
    remaining = datetime.fromtimestamp(token["exp"], UTC) - datetime.now(UTC)
    assert remaining <= PREAUTH_TOKEN_LIFETIME
    assert remaining.total_seconds() > PREAUTH_TOKEN_LIFETIME.total_seconds() - 60


def test_the_new_staff_account_cannot_log_into_the_admin(owner_client, mailbox):
    """**THE HOLE TASK 3b CLOSED**, now asserted as closed.

    Until 3b this test asserted the opposite, with a note addressed to whoever built
    TOTP. The password an invite sets is real and the account is `is_staff`, so
    `/auth/admin-token/` minted a full admin session for it — which meant the preauth
    token accept-invite so carefully returned was a fence around a door that was still
    open, and Amendment 6's invariant ("the `toke-admin` claim means password +
    Turnstile + TOTP") was a description of an intention.

    The password step now mints nothing at all. A newly invited administrator holds a
    real password and reaches exactly one thing with it: the TOTP enrolment they owe.
    """
    from apps.accounts.authentication import ADMIN_AUDIENCE_CLAIM, ADMIN_PREAUTH_AUDIENCE
    from rest_framework_simplejwt.tokens import AccessToken

    _response, raw = invite_for(owner_client, mailbox)
    APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")

    r = APIClient().post(
        "/api/v1/auth/admin-token/",
        {"email": "newhire@toke.test", "password": NEW_PW},
        format="json",
    )
    assert r.status_code == 200
    assert "access" not in r.data and "refresh" not in r.data, (
        "a correct staff password must not produce an admin session — TOTP confirm is "
        "the only mint"
    )
    assert AccessToken(r.data["preauth_token"])[ADMIN_AUDIENCE_CLAIM] == ADMIN_PREAUTH_AUDIENCE
    assert r.data["totp_enrolled"] is False

    # And that preauth token is worth nothing on the admin surface.
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['preauth_token']}")
    assert client.get(ADMIN_ME).status_code == 401
    assert client.get("/api/v1/admin/orders/").status_code == 401


# --- accept: every way an invite can be refused -------------------------------


def test_an_expired_invite_is_refused(owner_client, mailbox, django_user_model):
    from apps.accounts.models import StaffInvite

    _response, raw = invite_for(owner_client, mailbox)
    StaffInvite.objects.update(expires_at=timezone.now() - timezone.timedelta(seconds=1))

    r = APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    assert r.status_code == 400
    assert "expired" in str(r.data).lower()
    assert not django_user_model.objects.filter(email="newhire@toke.test").exists()


def test_a_revoked_invite_is_refused(owner_client, mailbox, django_user_model):
    response, raw = invite_for(owner_client, mailbox)
    owner_client.post(revoke_url(response.data["id"]))

    r = APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    assert r.status_code == 400
    assert not django_user_model.objects.filter(email="newhire@toke.test").exists()


def test_a_used_invite_is_refused(owner_client, mailbox):
    _response, raw = invite_for(owner_client, mailbox)
    assert APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json").status_code == 200
    again = APIClient().post(ACCEPT, {"token": raw, "password": "Third!pass42"}, format="json")
    assert again.status_code == 400


def test_invalid_and_revoked_share_one_message(owner_client, mailbox):
    """Distinguishing them would turn the endpoint into an oracle that confirms a token
    was once real — which is exactly the feedback an attacker who scraped a mailbox, a
    proxy log or a browser history needs to know they have something worth using."""
    response, raw = invite_for(owner_client, mailbox)
    owner_client.post(revoke_url(response.data["id"]))

    revoked = APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    unknown = APIClient().post(
        ACCEPT, {"token": "not-a-real-token-at-all", "password": NEW_PW}, format="json"
    )
    assert revoked.status_code == unknown.status_code
    assert revoked.json() == unknown.json()


def test_a_used_invite_shares_that_same_message(owner_client, mailbox):
    _response, raw = invite_for(owner_client, mailbox)
    APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")

    used = APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    unknown = APIClient().post(
        ACCEPT, {"token": "not-a-real-token-at-all", "password": NEW_PW}, format="json"
    )
    assert used.json() == unknown.json()


def test_expiry_is_the_one_distinguishable_failure(owner_client, mailbox):
    """A deliberate exception to the uniform message: only someone holding a GENUINE
    token can ever see it, so it tells an attacker nothing, and "your link expired, ask
    for another" is the difference between a new hire who re-invites themselves and one
    who reports the admin as broken."""
    _response, raw = invite_for(owner_client, mailbox)
    from apps.accounts.models import StaffInvite

    StaffInvite.objects.update(expires_at=timezone.now() - timezone.timedelta(seconds=1))

    expired = APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    unknown = APIClient().post(
        ACCEPT, {"token": "not-a-real-token-at-all", "password": NEW_PW}, format="json"
    )
    assert expired.json() != unknown.json()


def test_a_weak_password_does_not_consume_the_invite(owner_client, mailbox):
    """The invite is claimed AFTER the password is validated. The other order burns a
    single-use capability on a typo and leaves the new hire with no way back in."""
    from apps.accounts.models import StaffInvite

    _response, raw = invite_for(owner_client, mailbox)
    r = APIClient().post(ACCEPT, {"token": raw, "password": "abc"}, format="json")
    assert r.status_code == 400
    assert StaffInvite.objects.get().accepted_at is None

    ok = APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    assert ok.status_code == 200


def test_a_failed_accept_logs_at_error(owner_client, mailbox, caplog):
    """There is no benign way to submit a token that never existed: the only legitimate
    callers are holding one out of their own inbox. ERROR is the level Sentry turns into
    an event."""
    with caplog.at_level(logging.INFO, logger="apps.security"):
        APIClient().post(
            ACCEPT, {"token": "not-a-real-token-at-all", "password": NEW_PW}, format="json"
        )
    assert any(
        "staff invite accept failed" in rec.getMessage()
        for rec in _security_records(caplog, logging.ERROR)
    )


def test_an_expired_accept_is_not_an_alert(owner_client, mailbox, caplog):
    """The one refusal with a boring explanation — a real new hire who waited too long.
    Paging on it would train whoever reads Sentry to dismiss the alert that matters."""
    from apps.accounts.models import StaffInvite

    _response, raw = invite_for(owner_client, mailbox)
    StaffInvite.objects.update(expires_at=timezone.now() - timezone.timedelta(seconds=1))

    with caplog.at_level(logging.INFO, logger="apps.security"):
        caplog.clear()
        APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    assert not _security_records(caplog, logging.ERROR)


def test_a_failed_accept_never_logs_the_submitted_token(owner_client, mailbox, caplog):
    """A token in a log line is a staff-creation capability in a log line — and the
    logs go to Sentry, where more people can read them than can read a mailbox."""
    _response, raw = invite_for(owner_client, mailbox)
    APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")

    with caplog.at_level(logging.INFO):
        caplog.clear()
        APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    assert not any(raw in rec.getMessage() for rec in caplog.records)


def test_a_forged_client_ip_cannot_forge_a_log_line(client, caplog):
    """`client_ip` reads CF-Connecting-IP, which is only unforgeable because the origin
    accepts nothing but Cloudflare. On the direct-to-API path it is attacker text going
    straight into a plain-text log line, so it goes through `scrub` first — same lesson
    as the login email field."""
    with caplog.at_level(logging.INFO, logger="apps.security"):
        client.post(
            ACCEPT,
            {"token": "junk", "password": NEW_PW},
            content_type="application/json",
            HTTP_CF_CONNECTING_IP="1.2.3.4\nstaff invite accepted for attacker@evil.test",
        )
    assert not any(
        "\n" in rec.getMessage() for rec in caplog.records
    ), "a newline in CF-Connecting-IP forged an extra security log line"


# --- accept: the existing-customer case ---------------------------------------


def test_an_existing_customer_is_promoted_rather_than_duplicated(
    owner_client, mailbox, django_user_model
):
    """RULED: promote. Refusing breaks the only real user — the store owner shops on his
    own store — and creating a second account is a unique-constraint violation
    pretending to be an option."""
    customer = django_user_model.objects.create_user(email="shopper@toke.test", password=PW)
    _response, raw = invite_for(owner_client, mailbox, email="shopper@toke.test", role="Manager")

    r = APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    assert r.status_code == 200

    assert django_user_model.objects.filter(email="shopper@toke.test").count() == 1
    customer.refresh_from_db()
    assert customer.is_staff is True
    assert list(customer.groups.values_list("name", flat=True)) == ["Manager"]


def test_promotion_overwrites_the_customer_era_password(
    owner_client, mailbox, django_user_model
):
    """THE reason the accept flow always sets a password rather than only doing so for
    new accounts. Without it a shopping password — chosen years ago, possibly reused,
    possibly in a breach corpus — silently becomes an administrator's password.

    Possession of the invite token proves control of the inbox, which is exactly the
    trust level `/auth/password/reset/` already runs on. This is reset-with-promotion,
    nothing weaker.
    """
    customer = django_user_model.objects.create_user(email="shopper@toke.test", password=PW)
    _response, raw = invite_for(owner_client, mailbox, email="shopper@toke.test")
    APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")

    customer.refresh_from_db()
    assert not customer.check_password(PW), "the customer-era password still works"
    assert customer.check_password(NEW_PW)


def test_a_promoted_users_old_customer_session_can_never_become_an_admin_one(
    owner_client, mailbox, django_user_model
):
    """The rider on the promotion ruling, verified rather than asserted. Promotion does
    not blacklist the customer's outstanding refresh tokens, so a session opened before
    the promotion keeps working on the storefront. That is acceptable because the admin
    audience claim is minted in exactly one place (`AdminTokenObtainPairSerializer`) and
    refresh only ever copies claims that are already present — so no amount of
    refreshing can grow one."""
    from apps.accounts.authentication import ADMIN_AUDIENCE_CLAIM
    from rest_framework_simplejwt.tokens import AccessToken

    django_user_model.objects.create_user(email="shopper@toke.test", password=PW)
    client = APIClient()
    login = client.post(CUSTOMER_TOKEN, {"email": "shopper@toke.test", "password": PW}, format="json")
    old_refresh = login.data["refresh"]

    _response, raw = invite_for(owner_client, mailbox, email="shopper@toke.test")
    APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")

    refreshed = client.post("/api/v1/auth/token/refresh/", {"refresh": old_refresh}, format="json")
    assert refreshed.status_code == 200, "the pre-promotion customer session still works"
    assert AccessToken(refreshed.data["access"]).get(ADMIN_AUDIENCE_CLAIM) is None

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refreshed.data['access']}")
    assert client.get(ADMIN_ME).status_code == 401


# --- accept: Turnstile --------------------------------------------------------


def test_accept_is_turnstile_gated_on_the_admin_widget(owner_client, mailbox, settings, monkeypatch):
    """A public endpoint that creates administrators. It verifies against
    `admin_turnstile_secret()` — the admin widget if one is configured, the customer one
    otherwise — because the accept page is served by the admin app's hostname and
    Turnstile widgets are domain-scoped."""
    _response, raw = invite_for(owner_client, mailbox)
    settings.TURNSTILE_ADMIN_SECRET = "sk-admin"
    recorder = _siteverify(monkeypatch)

    client = APIClient()
    assert client.post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json").status_code == 403

    ok = client.post(
        ACCEPT, {"token": raw, "password": NEW_PW, "turnstile_token": "tok"}, format="json"
    )
    assert ok.status_code == 200
    assert recorder.calls[-1]["data"] == {"secret": "sk-admin", "response": "tok"}


def test_a_turnstile_rejection_does_not_consume_the_invite(
    owner_client, mailbox, settings, monkeypatch
):
    from apps.accounts.models import StaffInvite

    _response, raw = invite_for(owner_client, mailbox)
    settings.TURNSTILE_ADMIN_SECRET = "sk-admin"
    _siteverify(monkeypatch, success=False)

    r = APIClient().post(
        ACCEPT, {"token": raw, "password": NEW_PW, "turnstile_token": "tok"}, format="json"
    )
    assert r.status_code == 403
    assert StaffInvite.objects.get().accepted_at is None


# --- accept: the inverted throttle --------------------------------------------
# THE REASONING, because it is the opposite of what a reviewer expects to see.
#
# Every other throttle in this project is checked in `initial()`, before the request
# has proved anything. On this endpoint that would be a denial button: accept traffic
# arrives via the Task 5 BFF from Vercel egress, i.e. ONE shared IP bucket, and the
# legitimate new hire gets exactly one shot. An attacker who fills the bucket with junk
# would 429 the only person the endpoint exists for.
#
# So the order is inverted: Turnstile -> hash -> indexed lookup -> if the token is
# VALID, proceed and touch no bucket at all -> only an INVALID token is counted. That is
# safe precisely because the token is 256 bits of entropy: an attacker cannot manufacture
# the bypass condition without already holding the capability the bucket protects.


def _accept_bucket():
    from apps.accounts.throttling import StaffInviteAcceptThrottle

    class _Req:
        META = {"REMOTE_ADDR": "127.0.0.1"}

    throttle = StaffInviteAcceptThrottle()
    return throttle, throttle.get_cache_key(_Req(), view=None)


def test_a_valid_accept_touches_no_throttle_bucket(owner_client, mailbox):
    """New-hire lockout is made structurally impossible rather than merely unlikely."""
    _response, raw = invite_for(owner_client, mailbox)
    throttle, key = _accept_bucket()

    r = APIClient().post(ACCEPT, {"token": raw, "password": NEW_PW}, format="json")
    assert r.status_code == 200
    assert throttle.cache.get(key, []) == [], "a legitimate accept spent the shared allowance"


def test_an_invalid_token_does_increment_the_bucket(client):
    throttle, key = _accept_bucket()
    r = client.post(
        ACCEPT, {"token": "junk-token", "password": NEW_PW}, content_type="application/json"
    )
    assert r.status_code == 400
    assert len(throttle.cache.get(key, [])) == 1


def test_invalid_tokens_are_eventually_capped(client):
    codes = [
        client.post(
            ACCEPT, {"token": f"junk-{i}", "password": NEW_PW}, content_type="application/json"
        ).status_code
        for i in range(14)
    ]
    assert 429 in codes, "guessing invite tokens was completely unmetered"


def test_a_capped_attacker_still_cannot_lock_the_new_hire_out(owner_client, mailbox, client):
    """The whole point, end to end. An attacker exhausts the shared bucket; the person
    the invite was actually sent to still gets in."""
    _response, raw = invite_for(owner_client, mailbox)
    for i in range(14):
        client.post(
            ACCEPT, {"token": f"junk-{i}", "password": NEW_PW}, content_type="application/json"
        )

    ok = client.post(
        ACCEPT, {"token": raw, "password": NEW_PW}, content_type="application/json"
    )
    assert ok.status_code == 200, "a stranger denied the new hire their one shot"


def test_a_malformed_accept_body_consumes_nothing(client):
    """Not a token guess: it never reached the lookup, so it must not spend the shared
    allowance — the same lesson `_FailureCountingMixin` was written for."""
    throttle, key = _accept_bucket()
    r = client.post(ACCEPT, {"password": NEW_PW}, content_type="application/json")
    assert r.status_code == 400
    assert throttle.cache.get(key, []) == []


# --- single use under concurrency ---------------------------------------------


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="A real conditional-UPDATE race needs PostgreSQL; SQLite serialises writes.",
)
class AcceptRaceTest(TransactionTestCase):
    """Single-use has to survive two accepts arriving at once.

    Check-then-set loses this race: both requests read `accepted_at IS NULL`, both
    proceed, and the second either creates a duplicate account or overwrites the first
    one's password. The claim is therefore ONE conditional UPDATE — the database
    evaluates the predicate while holding the row lock, so exactly one call sees a
    rowcount of 1.

    `TransactionTestCase` rather than the usual pytest-django harness because the
    default wraps each test in a transaction that never commits, which would hide the
    race entirely: both threads would sit inside the same outer transaction.
    """

    serialized_rollback = True  # restore the migration-seeded role groups after the flush

    def test_two_concurrent_accepts_yield_exactly_one_staff_account(self):
        from django.contrib.auth import get_user_model

        from apps.accounts.invites import InviteRejected, accept_invite, issue_invite

        User = get_user_model()
        inviter = User.objects.create_user(email="owner@race.test", password=PW, is_staff=True)
        inviter.groups.add(Group.objects.get(name="Owner"))
        _invite, raw = issue_invite(
            email="race@toke.test", role=Group.objects.get(name="Support"), invited_by=inviter
        )

        barrier = threading.Barrier(2)
        results = []

        def worker():
            barrier.wait()
            try:
                accept_invite(raw, password=NEW_PW)
                results.append("ok")
            except InviteRejected:
                results.append("rejected")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == ["ok", "rejected"], results
        assert User.objects.filter(email="race@toke.test").count() == 1
        assert User.objects.get(email="race@toke.test").is_staff is True


# --- the migration ------------------------------------------------------------


def test_the_invite_migration_cannot_destroy_data_on_the_way_back():
    """The lesson `accounts/0003` paid for: a reverse that deletes rows the forward did
    not create is not a reverse. This migration is schema-only — it creates one table
    that nothing else references and holds nothing but invites — so dropping it undoes
    exactly what it did and no more. A `RunPython` here would reintroduce the class of
    bug, so the absence of one is asserted rather than assumed."""
    from importlib import import_module

    from django.db import migrations

    module = import_module("apps.accounts.migrations.0004_staffinvite")
    for operation in module.Migration.operations:
        assert not isinstance(operation, (migrations.RunPython, migrations.RunSQL)), (
            f"{operation} can touch rows the forward migration did not create"
        )


def test_deleting_a_role_group_with_outstanding_invites_fails_loudly(owner_client, mailbox):
    """PROTECT, not CASCADE or SET_NULL. An orphaned invite is a token that grants a
    role nobody can name; a loud failure is the only outcome that gets looked at."""
    from django.db.models import ProtectedError

    invite_for(owner_client, mailbox, role="Support")
    with pytest.raises(ProtectedError):
        Group.objects.get(name="Support").delete()
