"""Email OTP and trusted devices — the Plan-33 widening of the second factor.

Two features, one file, because they share a security argument:

* EMAIL CODES are a second METHOD for the same factor step — chosen at first login,
  proved by control of the inbox, verified at the same confirm endpoint that mints.
  The property these tests defend is that the weaker method can never SUBSTITUTE for
  the stronger one: a confirmed TOTP enrolment refuses both the email send and an
  email-method confirm, so a stolen password cannot downgrade an authenticator user.

* TRUSTED DEVICES are a PRE-VERIFIED second factor, never a bypass: issued only
  alongside a real code, redeemed only at confirm behind a preauth token (password +
  Turnstile still ran), scoped to the user, hard-expired at 30 days, and voided
  wholesale by recovery and by the revoke endpoint.

`test_staff_totp.py` still owns the ceremony fundamentals (one mint, four preauth
destinations, the brute-force layers); this file leans on its helpers rather than
restating them.
"""
import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import (
    StaffEmailSecondFactor,
    StaffRecoveryCode,
    StaffTOTP,
    StaffTrustedDevice,
)
from apps.accounts.tests.test_staff_totp import (
    ADMIN_ME,
    ADMIN_TOKEN,
    CONFIRM,
    EMAIL_OTP,
    ENROL,
    PW,
    RECOVERY,
    bearer,
    full_ceremony,
    preauth_for,
)

pytestmark = pytest.mark.django_db

REVOKE_DEVICES = "/api/v1/auth/admin-devices/revoke/"


@pytest.fixture
def owner(django_user_model):
    user = django_user_model.objects.create_user(
        email="owner@toke.test", password=PW, is_staff=True, first_name="Toke"
    )
    user.groups.add(Group.objects.get(name="Owner"))
    return user


@pytest.fixture
def second_owner(django_user_model):
    user = django_user_model.objects.create_user(
        email="second@toke.test", password=PW, is_staff=True
    )
    user.groups.add(Group.objects.get(name="Owner"))
    return user


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Codes, cooldowns and failure counters all live in the cache; a leftover
    cooldown from one test must not eat the next test's send."""
    cache.clear()
    yield
    cache.clear()


def sent_code() -> str:
    """The six digits out of the most recent OTP email — read from the subject, which
    carries the code so phone notifications show it without opening the mail."""
    assert mail.outbox, "no OTP email was sent"
    return mail.outbox[-1].subject.split()[0]


def request_code(preauth):
    return bearer(preauth).post(EMAIL_OTP, {}, format="json")


def confirm_email(preauth, code, *, trust_device=False):
    body = {"method": "email", "code": code}
    if trust_device:
        body["trust_device"] = True
    return bearer(preauth).post(CONFIRM, body, format="json")


def email_ceremony(user, *, trust_device=False):
    """password -> preauth -> email code -> confirm. Returns the confirm response.

    Clears the send caps first: a test that runs several ceremonies is many logins
    compressed into one second, and the cooldown that is correct in production would
    otherwise turn the second request into a polite no-send."""
    from apps.accounts import email_otp

    cache.delete(email_otp._cooldown_key(user))
    cache.delete(email_otp._sends_key(user))
    mail.outbox = []
    preauth = preauth_for(user)
    assert request_code(preauth).status_code == 200
    r = confirm_email(preauth, sent_code(), trust_device=trust_device)
    assert r.status_code == 200, r.data
    return r


# --- the login response tells the admin app which screen to draw -----------------


def test_login_reports_no_second_factor_for_a_fresh_account(owner):
    r = APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    assert r.status_code == 200
    assert r.data["second_factor"] is None
    assert r.data["device_trusted"] is False
    assert r.data["totp_enrolled"] is False  # the pre-Plan-33 field still answers


def test_login_reports_the_method_the_account_confirmed(owner, second_owner):
    email_ceremony(owner)
    r = APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    assert r.data["second_factor"] == "email"
    assert r.data["totp_enrolled"] is False

    full_ceremony(second_owner)
    r = APIClient().post(
        ADMIN_TOKEN, {"email": second_owner.email, "password": PW}, format="json"
    )
    assert r.data["second_factor"] == "totp"
    assert r.data["totp_enrolled"] is True


# --- email OTP: enrolment and ordinary login -------------------------------------


def test_the_first_verified_email_code_enrols_and_issues_recovery_codes(owner):
    r = email_ceremony(owner)
    assert "access" in r.data and "refresh" in r.data
    assert len(r.data["recovery_codes"]) == 8
    assert StaffEmailSecondFactor.objects.get(user=owner).is_confirmed
    # The session is real: it opens the admin surface.
    assert bearer(r.data["access"]).get(ADMIN_ME).status_code == 200


def test_an_ordinary_email_login_issues_no_new_recovery_codes(owner):
    email_ceremony(owner)
    r = email_ceremony(owner)
    assert "recovery_codes" not in r.data


def test_the_code_goes_only_to_the_token_holders_own_inbox(owner):
    """The endpoint takes no body worth having: the address comes off the validated
    token's user, so there is nothing a caller can aim."""
    mail.outbox = []
    preauth = preauth_for(owner)
    r = bearer(preauth).post(EMAIL_OTP, {"email": "attacker@evil.test"}, format="json")
    assert r.status_code == 200
    assert [m.to for m in mail.outbox] == [[owner.email]]
    assert "attacker@evil.test" not in str(mail.outbox[-1].message())


def test_a_wrong_email_code_is_refused_and_a_used_one_cannot_replay(owner):
    mail.outbox = []
    preauth = preauth_for(owner)
    assert request_code(preauth).status_code == 200
    code = sent_code()

    wrong = f"{(int(code) + 1) % 1000000:06d}"
    assert confirm_email(preauth, wrong).status_code == 401

    assert confirm_email(preauth, code).status_code == 200
    # Single-use: the same code again is dead, on a fresh preauth too.
    preauth2 = preauth_for(owner)
    assert confirm_email(preauth2, code).status_code == 401


def test_an_expired_code_is_refused(owner, monkeypatch):
    mail.outbox = []
    preauth = preauth_for(owner)
    assert request_code(preauth).status_code == 200
    code = sent_code()

    from apps.accounts import email_otp

    # The cache key carries CODE_LIFETIME as its TTL; simulate expiry the way it
    # happens in production — the entry is gone.
    cache.delete(email_otp._code_key(owner))
    assert confirm_email(preauth, code).status_code == 401


# --- email OTP: the downgrade refusals -------------------------------------------


def test_a_totp_account_cannot_be_sent_an_email_code(owner):
    full_ceremony(owner)
    preauth = preauth_for(owner)
    mail.outbox = []
    r = request_code(preauth)
    assert r.status_code == 409
    assert mail.outbox == []


def test_a_totp_account_refuses_an_email_method_confirm_outright(owner):
    """Even with a code somehow in hand (a race with enrolment, a cache edit), the
    method itself is refused for an authenticator account."""
    full_ceremony(owner)
    preauth = preauth_for(owner)
    assert confirm_email(preauth, "123456").status_code == 401


def test_an_email_account_refuses_totp_enrolment(owner):
    """The mirror image: a stolen password must not move an email account's factor
    onto an attacker's authenticator app."""
    email_ceremony(owner)
    preauth = preauth_for(owner)
    assert bearer(preauth).post(ENROL, {}, format="json").status_code == 409


# --- email OTP: send caps --------------------------------------------------------


def test_a_second_send_inside_the_cooldown_is_a_polite_200_and_no_mail(owner):
    mail.outbox = []
    preauth = preauth_for(owner)
    assert request_code(preauth).status_code == 200
    assert len(mail.outbox) == 1

    r = request_code(preauth)
    assert r.status_code == 200
    assert r.data["retry_after"] > 0
    assert len(mail.outbox) == 1  # reassurance, not a resend


def test_the_hourly_send_cap_answers_429(owner, monkeypatch):
    from apps.accounts import email_otp

    monkeypatch.setattr(email_otp, "SEND_COOLDOWN", 0)
    preauth = preauth_for(owner)
    for _ in range(email_otp.SEND_LIMIT):
        assert request_code(preauth).status_code == 200
    assert request_code(preauth).status_code == 429


def test_five_wrong_guesses_void_the_code_itself(owner):
    from apps.accounts import email_otp

    mail.outbox = []
    preauth = preauth_for(owner)
    assert request_code(preauth).status_code == 200
    code = sent_code()

    # Five wrong guesses ride under the per-preauth limit only because they are the
    # same limit (5); use four here so the PREAUTH token survives and what this test
    # observes is the CODE dying.
    wrong = f"{(int(code) + 1) % 1000000:06d}"
    for _ in range(email_otp.CODE_ATTEMPT_LIMIT - 1):
        assert confirm_email(preauth, wrong).status_code == 401
    assert cache.get(email_otp._attempts_key(owner)) == email_otp.CODE_ATTEMPT_LIMIT - 1

    # The fifth wrong guess voids the code; the right answer is now dead too.
    confirm_email(preauth, wrong)
    preauth2 = preauth_for(owner)
    assert confirm_email(preauth2, code).status_code == 401


# --- trusted devices: issuance ---------------------------------------------------


def test_trust_is_issued_only_when_asked_for_and_alongside_a_real_code(owner):
    r = email_ceremony(owner)
    assert "device_token" not in r.data  # not asked for

    r = email_ceremony(owner, trust_device=True)
    assert r.data["device_token"]
    assert r.data["device_expires_in"] == 30 * 24 * 3600
    row = StaffTrustedDevice.objects.get(user=owner)
    assert row.expires_at > timezone.now()


def test_totp_logins_can_earn_trust_too(owner, monkeypatch):
    import time

    import pyotp

    from apps.accounts.tests.test_staff_totp import Clock

    clock = Clock(monkeypatch)
    preauth = preauth_for(owner)
    secret = bearer(preauth).post(ENROL, {}, format="json").data["secret"]
    r = bearer(preauth).post(CONFIRM, {"code": clock.code(secret)}, format="json")
    assert r.status_code == 200, r.data

    # A later step, so the replay guard admits the second code.
    clock.advance(60)
    preauth2 = preauth_for(owner)
    r2 = bearer(preauth2).post(
        CONFIRM, {"code": clock.code(secret), "trust_device": True}, format="json"
    )
    assert r2.status_code == 200, r2.data
    assert r2.data["device_token"]


# --- trusted devices: the login hint and redemption ------------------------------


def test_a_trusted_device_skips_the_code_and_only_the_code(owner):
    device = email_ceremony(owner, trust_device=True).data["device_token"]

    # The hint at the password step...
    r = APIClient().post(
        ADMIN_TOKEN,
        {"email": owner.email, "password": PW, "device_token": device},
        format="json",
    )
    assert r.status_code == 200
    assert r.data["device_trusted"] is True
    assert "access" not in r.data  # still a preauth token, still no session

    # ...and redemption at confirm. No code anywhere in this ceremony.
    r2 = bearer(r.data["preauth_token"]).post(
        CONFIRM, {"method": "trusted_device", "device_token": device}, format="json"
    )
    assert r2.status_code == 200, r2.data
    assert "recovery_codes" not in r2.data
    assert bearer(r2.data["access"]).get(ADMIN_ME).status_code == 200
    assert StaffTrustedDevice.objects.get(user=owner).last_used_at is not None


def test_a_trusted_device_never_earns_fresh_trust(owner):
    """Trust chaining would make the 30-day ceiling a fiction: each silent login
    would mint another 30 days."""
    device = email_ceremony(owner, trust_device=True).data["device_token"]
    preauth = preauth_for(owner)
    r = bearer(preauth).post(
        CONFIRM,
        {"method": "trusted_device", "device_token": device, "trust_device": True},
        format="json",
    )
    assert r.status_code == 200
    assert "device_token" not in r.data
    assert StaffTrustedDevice.objects.filter(user=owner).count() == 1


def test_an_expired_device_is_refused_and_the_hint_agrees(owner):
    device = email_ceremony(owner, trust_device=True).data["device_token"]
    StaffTrustedDevice.objects.filter(user=owner).update(
        expires_at=timezone.now() - timezone.timedelta(seconds=1)
    )

    r = APIClient().post(
        ADMIN_TOKEN,
        {"email": owner.email, "password": PW, "device_token": device},
        format="json",
    )
    assert r.data["device_trusted"] is False
    r2 = bearer(r.data["preauth_token"]).post(
        CONFIRM, {"method": "trusted_device", "device_token": device}, format="json"
    )
    assert r2.status_code == 401


def test_one_users_device_is_worthless_against_anothers_account(owner, second_owner):
    device = email_ceremony(owner, trust_device=True).data["device_token"]
    email_ceremony(second_owner)

    preauth = preauth_for(second_owner)
    r = bearer(preauth).post(
        CONFIRM, {"method": "trusted_device", "device_token": device}, format="json"
    )
    assert r.status_code == 401


def test_a_device_token_alone_opens_nothing(owner):
    """No preauth, no entry: the trusted-device cookie is a second factor, and the
    password step still stands in front of it."""
    device = email_ceremony(owner, trust_device=True).data["device_token"]
    r = APIClient().post(
        CONFIRM, {"method": "trusted_device", "device_token": device}, format="json"
    )
    assert r.status_code == 401


# --- trusted devices: revocation -------------------------------------------------


def test_recovery_voids_the_email_factor_and_every_trusted_device(owner):
    r = email_ceremony(owner, trust_device=True)
    codes = r.data["recovery_codes"]
    device = r.data["device_token"]

    preauth = preauth_for(owner)
    rec = bearer(preauth).post(RECOVERY, {"code": codes[0]}, format="json")
    assert rec.status_code == 200
    assert rec.data["enrolment_required"] is True

    assert not StaffEmailSecondFactor.objects.filter(user=owner).exists()
    assert not StaffTrustedDevice.objects.filter(user=owner).exists()
    assert not StaffRecoveryCode.objects.filter(user=owner).exists()
    assert not StaffTOTP.objects.filter(user=owner).exists()

    # The dead device is refused; the account is back at the method choice.
    r2 = APIClient().post(
        ADMIN_TOKEN,
        {"email": owner.email, "password": PW, "device_token": device},
        format="json",
    )
    assert r2.data["second_factor"] is None
    assert r2.data["device_trusted"] is False


def test_the_revoke_endpoint_kills_every_device_and_needs_a_full_session(owner):
    r = email_ceremony(owner, trust_device=True)
    device = r.data["device_token"]

    # A preauth token is not enough to revoke — it is not an admin session.
    preauth = preauth_for(owner)
    assert bearer(preauth).post(REVOKE_DEVICES, {}, format="json").status_code == 401

    out = bearer(r.data["access"]).post(REVOKE_DEVICES, {}, format="json")
    assert out.status_code == 200
    assert out.data["revoked"] == 1
    assert not StaffTrustedDevice.objects.filter(user=owner).exists()

    # The cookie the browser still holds is now worthless.
    r2 = APIClient().post(
        ADMIN_TOKEN,
        {"email": owner.email, "password": PW, "device_token": device},
        format="json",
    )
    assert r2.data["device_trusted"] is False


def test_trust_rows_are_capped_per_user(owner):
    from apps.accounts.devices import MAX_DEVICES_PER_USER

    for _ in range(MAX_DEVICES_PER_USER + 3):
        email_ceremony(owner, trust_device=True)
    assert StaffTrustedDevice.objects.filter(user=owner).count() == MAX_DEVICES_PER_USER
