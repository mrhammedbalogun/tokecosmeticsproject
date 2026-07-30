"""Mandatory staff TOTP — the second factor that makes the admin audience claim mean
what Amendment 6 says it means.

WHAT WAS TRUE BEFORE THIS FILE EXISTED. Accepting a staff invite correctly returned a
*preauth* token, but the account it created had a working password, and
`/auth/admin-token/` handed out a full admin session for a password alone. The
preauth token was therefore a speed bump around a door that was still open. Amendment
6's invariant — "the `toke-admin` claim means password + Turnstile + TOTP, and is
minted nowhere else" — was aspirational. These tests are what make it true.

THE CEREMONY, in one place, because every test below is a slice of it:

    POST /auth/admin-token/       password + Turnstile  -> PREAUTH token (always)
    POST /auth/admin-totp/enrol/  preauth               -> secret + provisioning URI
    POST /auth/admin-totp/confirm/ preauth + code       -> ADMIN token pair (only here)
    POST /auth/admin-totp/recovery/ preauth + code      -> voids TOTP, mints nothing

`/auth/admin-token/` returns a preauth token whether or not the caller has enrolled.
One bootstrap path, not two — a second path is where the hole grows, and it also
means the mint lives in exactly one place, which is what
`test_admin_surface_guard.py` can then assert forever.

THE BRUTE-FORCE ARGUMENT, because a reader will otherwise ask why there are two
layers for a six-digit code. The caller holds a validated preauth token, so the
natural key is the USER — unforgeable, unshared, and structurally not a denial button
(only someone holding the staff password can burn it). But per-preauth invalidation
ALONE is not a fence: an attacker holding the password performs *successful* password
authentications, so the failure-counting admin-login throttles never increment, and
the only cost per ceremony is one solved Turnstile token. With +/-1 step of drift
there are about three valid codes at any moment (p ~ 3e-6); at 5 guesses per preauth
that is ~46,000 ceremonies — about $46 of solver tokens — for even odds. The
per-user, per-hour cap is what actually caps it (~480 days to a coin flip) and it
raises a Sentry event in the first hour.
"""
import hashlib
import logging
import threading
import time

import pyotp
import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TransactionTestCase
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PW = "Str0ng!pass9"

ADMIN_TOKEN = "/api/v1/auth/admin-token/"
ADMIN_ME = "/api/v1/auth/admin-me/"
ENROL = "/api/v1/auth/admin-totp/enrol/"
CONFIRM = "/api/v1/auth/admin-totp/confirm/"
RECOVERY = "/api/v1/auth/admin-totp/recovery/"

# The three endpoints a preauth token is allowed to reach, and nothing else.
PREAUTH_ENDPOINTS = (ENROL, CONFIRM, RECOVERY)


# --- fixtures -----------------------------------------------------------------


@pytest.fixture
def owner(django_user_model):
    user = django_user_model.objects.create_user(
        email="owner@toke.test", password=PW, is_staff=True, first_name="Toke", last_name="Owner"
    )
    user.groups.add(Group.objects.get(name="Owner"))
    return user


@pytest.fixture
def superuser(django_user_model):
    return django_user_model.objects.create_superuser(email="root@toke.test", password=PW)


@pytest.fixture
def customer(django_user_model):
    return django_user_model.objects.create_user(email="shopper@toke.test", password=PW)


class Clock:
    """Pins the SERVER's TOTP clock so a test can step it forward deliberately.

    Needed because two successful verifications in one test cannot both use the current
    step — the replay guard refuses the second, correctly. Generating a code for a
    future timestamp is not enough on its own: the server would still be in the present
    and would reject it as drift. Both sides have to move, so this owns both.
    """

    def __init__(self, monkeypatch):
        self.now = float(int(time.time()))
        monkeypatch.setattr("apps.accounts.totp._now", lambda: self.now)

    def advance(self, seconds: int = 60) -> None:
        self.now += seconds

    def code(self, secret: str) -> str:
        return pyotp.TOTP(secret).at(int(self.now))


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch)


# --- ceremony helpers ---------------------------------------------------------


def preauth_for(user, password=PW, client=None):
    """Step one: password (+ Turnstile, off in tests) -> preauth token."""
    client = client or APIClient()
    r = client.post(ADMIN_TOKEN, {"email": user.email, "password": password}, format="json")
    assert r.status_code == 200, r.data
    return r.data["preauth_token"]


def bearer(token) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def enrol(preauth):
    """Step two: get a secret. Returns the response data (secret + provisioning URI)."""
    r = bearer(preauth).post(ENROL, {}, format="json")
    assert r.status_code == 200, r.data
    return r.data


def code_for(secret, at=None) -> str:
    return pyotp.TOTP(secret).at(at if at is not None else int(time.time()))


def confirm(preauth, secret, clock=None):
    code = clock.code(secret) if clock is not None else code_for(secret)
    return bearer(preauth).post(CONFIRM, {"code": code}, format="json")


def full_ceremony(user, password=PW, clock=None):
    """password -> preauth -> enrol -> confirm. Returns `(secret, response_data)`.

    The response data is the ONLY place an admin token pair ever comes from, which is
    the point of routing every test that needs an admin session through here.
    """
    preauth = preauth_for(user, password)
    secret = enrol(preauth)["secret"]
    r = confirm(preauth, secret, clock)
    assert r.status_code == 200, r.data
    return secret, r.data


def admin_client(user, password=PW) -> APIClient:
    _secret, data = full_ceremony(user, password)
    return bearer(data["access"])


def _security_records(caplog, level=logging.INFO):
    return [
        rec for rec in caplog.records if rec.name == "apps.security" and rec.levelno >= level
    ]


# --- secrets and storage at rest ----------------------------------------------


def test_the_secret_is_160_bits_of_base32():
    """RFC 4226 §4 R6 recommends 160 bits. `pyotp.random_base32(length=32)` is 32
    base32 characters = 160 bits, and it is what every authenticator app expects."""
    from apps.accounts.totp import SECRET_LENGTH, new_secret

    secret = new_secret()
    assert len(secret) == SECRET_LENGTH == 32
    assert set(secret) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    assert new_secret() != secret


def test_the_stored_secret_round_trips_and_is_never_plaintext_in_the_column(owner):
    """The reason `cryptography` is a dependency at all. The nightly database backup
    leaves this box for S3; a plaintext TOTP secret in that dump is the second factor
    for every staff account, handed over for free. The ciphertext is checked against
    the RAW COLUMN, read back through the database, not against the Python attribute —
    the attribute could be right while the column held something else."""
    from django.db import connection

    from apps.accounts.models import StaffTOTP
    from apps.accounts.totp import decrypt_secret, encrypt_secret, new_secret

    secret = new_secret()
    row = StaffTOTP.objects.create(user=owner, secret_ciphertext=encrypt_secret(secret))

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT secret_ciphertext FROM accounts_stafftotp WHERE id = %s", [row.pk]
        )
        stored = cursor.fetchone()[0]

    assert secret not in stored
    assert stored.startswith("gAAAAA")  # Fernet's version byte, base64'd
    assert decrypt_secret(stored) == secret


def test_a_secret_written_under_the_previous_key_still_decrypts(settings):
    """Key rotation has to be doable without a flag day. `MultiFernet` encrypts with
    the primary key and decrypts with any listed key, which is the same shape as
    Django's own `SECRET_KEY_FALLBACKS`."""
    from cryptography.fernet import Fernet

    from apps.accounts.totp import decrypt_secret, encrypt_secret, new_secret

    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    settings.TOTP_ENCRYPTION_KEY = old_key
    settings.TOTP_ENCRYPTION_KEY_FALLBACKS = []
    secret = new_secret()
    old_ciphertext = encrypt_secret(secret)

    settings.TOTP_ENCRYPTION_KEY = new_key
    settings.TOTP_ENCRYPTION_KEY_FALLBACKS = [old_key]
    assert decrypt_secret(old_ciphertext) == secret

    # And a value written now is under the NEW key, i.e. dropping the fallback later
    # is what completes the rotation.
    settings.TOTP_ENCRYPTION_KEY_FALLBACKS = []
    assert decrypt_secret(encrypt_secret(secret)) == secret
    with pytest.raises(Exception):
        decrypt_secret(old_ciphertext)


def test_rotate_totp_key_rewrites_every_row_under_the_primary_key(settings, owner):
    from cryptography.fernet import Fernet
    from django.core.management import call_command

    from apps.accounts.models import StaffTOTP
    from apps.accounts.totp import decrypt_secret, encrypt_secret, new_secret

    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    settings.TOTP_ENCRYPTION_KEY = old_key
    settings.TOTP_ENCRYPTION_KEY_FALLBACKS = []
    secret = new_secret()
    StaffTOTP.objects.create(user=owner, secret_ciphertext=encrypt_secret(secret))

    settings.TOTP_ENCRYPTION_KEY = new_key
    settings.TOTP_ENCRYPTION_KEY_FALLBACKS = [old_key]
    call_command("rotate_totp_key")

    # With the fallback removed the row must still decrypt — that is what proves it
    # was rewritten rather than merely still readable through the fallback.
    settings.TOTP_ENCRYPTION_KEY_FALLBACKS = []
    assert decrypt_secret(StaffTOTP.objects.get().secret_ciphertext) == secret


def test_the_provisioning_uri_names_the_issuer_and_the_account(owner):
    from urllib.parse import parse_qs, unquote, urlparse

    from apps.accounts.totp import ISSUER, new_secret, provisioning_uri

    uri = provisioning_uri(owner, new_secret())
    parsed = urlparse(uri)
    assert parsed.scheme == "otpauth" and parsed.netloc == "totp"
    assert unquote(parsed.path) == f"/{ISSUER}:{owner.email}"
    assert parse_qs(parsed.query)["issuer"] == [ISSUER]
    assert ISSUER == "Toke Cosmetics Admin"


# --- drift and replay ---------------------------------------------------------


def test_one_step_of_drift_is_accepted_in_both_directions():
    """+/-1 step = a 90-second acceptance window. Chosen over +/-2 deliberately: two
    steps doubles both the guess surface and the replay window, and buys nothing on a
    population whose server clock we control (the runbook's deploy check confirms NTP
    sync, because TOTP fails silently when a clock drifts)."""
    from apps.accounts.totp import TOTP_INTERVAL, verify_code

    secret = pyotp.random_base32()
    now = 1_800_000_000  # a fixed instant; the test must not depend on wall clock
    step = now // TOTP_INTERVAL

    assert verify_code(secret, code_for(secret, now), now=now) == step
    assert verify_code(secret, code_for(secret, now - TOTP_INTERVAL), now=now) == step - 1
    assert verify_code(secret, code_for(secret, now + TOTP_INTERVAL), now=now) == step + 1


def test_two_steps_of_drift_are_refused():
    from apps.accounts.totp import TOTP_INTERVAL, verify_code

    secret = pyotp.random_base32()
    now = 1_800_000_000

    assert verify_code(secret, code_for(secret, now - 2 * TOTP_INTERVAL), now=now) is None
    assert verify_code(secret, code_for(secret, now + 2 * TOTP_INTERVAL), now=now) is None


def test_a_replayed_code_is_refused(owner, monkeypatch):
    """A six-digit code is valid for 90 seconds, which is ample time for someone
    reading it off a shoulder, a screen share or a phished form to use it again.
    `last_verified_step` refuses any step at or below the last accepted one."""
    from apps.accounts.models import StaffTOTP

    secret, _data = full_ceremony(owner)
    step = StaffTOTP.objects.get(user=owner).last_verified_step
    assert step > 0

    preauth = preauth_for(owner)
    replay = bearer(preauth).post(
        CONFIRM, {"code": pyotp.TOTP(secret).at(step * 30)}, format="json"
    )
    assert replay.status_code == 401, replay.data


def test_a_code_from_an_earlier_step_is_refused_even_though_it_is_inside_the_window(
    owner, monkeypatch
):
    """The drift window and the replay guard are different rules and both apply. A
    code from step N-1 is inside the +/-1 window, so drift alone would accept it — but
    step N has already been consumed, so it must lose to the replay guard."""
    from apps.accounts.models import StaffTOTP
    from apps.accounts.totp import TOTP_INTERVAL

    _secret, _data = full_ceremony(owner)
    row = StaffTOTP.objects.get(user=owner)
    secret_step = row.last_verified_step

    from apps.accounts.totp import decrypt_secret

    secret = decrypt_secret(row.secret_ciphertext)
    preauth = preauth_for(owner)

    earlier = bearer(preauth).post(
        CONFIRM, {"code": pyotp.TOTP(secret).at((secret_step - 1) * TOTP_INTERVAL)},
        format="json",
    )
    assert earlier.status_code == 401

    # ...while the NEXT step is still accepted, or the guard is simply broken.
    later = bearer(preauth).post(
        CONFIRM, {"code": pyotp.TOTP(secret).at((secret_step + 1) * TOTP_INTERVAL)},
        format="json",
    )
    assert later.status_code == 200, later.data


# --- enrolment ----------------------------------------------------------------


def test_admin_token_returns_a_preauth_token_and_no_admin_pair(owner):
    """The change that makes Amendment 6 true. A correct staff password used to mint a
    full admin session; it now mints a ten-minute bootstrap credential that opens three
    endpoints."""
    from rest_framework_simplejwt.tokens import AccessToken

    from apps.accounts.authentication import ADMIN_AUDIENCE_CLAIM, ADMIN_PREAUTH_AUDIENCE

    r = APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    assert r.status_code == 200
    assert "access" not in r.data and "refresh" not in r.data
    assert AccessToken(r.data["preauth_token"])[ADMIN_AUDIENCE_CLAIM] == ADMIN_PREAUTH_AUDIENCE
    assert r.data["totp_enrolled"] is False


def test_admin_token_returns_a_preauth_token_for_an_ENROLLED_staff_member_too(owner):
    """One bootstrap path, not two. Enrolled or not, the password step produces the
    same kind of credential; only the client's next screen differs."""
    full_ceremony(owner)
    r = APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    assert r.status_code == 200
    assert "access" not in r.data and "refresh" not in r.data
    assert r.data["totp_enrolled"] is True


def test_enrol_then_confirm_mints_the_admin_pair_and_it_opens_the_admin(owner):
    from apps.accounts.authentication import ADMIN_AUDIENCE, ADMIN_AUDIENCE_CLAIM

    _secret, data = full_ceremony(owner)
    from rest_framework_simplejwt.tokens import AccessToken

    assert AccessToken(data["access"])[ADMIN_AUDIENCE_CLAIM] == ADMIN_AUDIENCE
    assert bearer(data["access"]).get(ADMIN_ME).status_code == 200


def test_confirm_issues_recovery_codes_exactly_once(owner, clock):
    from apps.accounts.models import StaffRecoveryCode
    from apps.accounts.totp import RECOVERY_CODE_COUNT

    secret, data = full_ceremony(owner, clock=clock)
    codes = data["recovery_codes"]
    assert len(codes) == RECOVERY_CODE_COUNT == 8
    assert all(len(c) == 20 for c in codes)  # secrets.token_hex(10) -> 80 bits
    assert StaffRecoveryCode.objects.filter(user=owner, used_at__isnull=True).count() == 8

    # A routine login (an already-confirmed enrolment) must NOT reissue them: a fresh
    # set every login would make the printed copy wrong within a day.
    clock.advance(60)
    again = confirm(preauth_for(owner), secret, clock)
    assert again.status_code == 200, again.data
    assert "recovery_codes" not in again.data
    assert StaffRecoveryCode.objects.filter(user=owner).count() == 8


def test_calling_enrol_again_replaces_an_UNCONFIRMED_secret(owner):
    """A half-finished enrolment must not strand anyone: someone who scanned a QR code
    into the wrong app, or closed the tab, calls enrol again and gets a fresh secret."""
    from apps.accounts.models import StaffTOTP

    preauth = preauth_for(owner)
    first = enrol(preauth)["secret"]
    second = enrol(preauth)["secret"]
    assert first != second

    from apps.accounts.totp import decrypt_secret

    assert decrypt_secret(StaffTOTP.objects.get(user=owner).secret_ciphertext) == second
    # And the first secret is now worthless.
    assert bearer(preauth).post(
        CONFIRM, {"code": code_for(first)}, format="json"
    ).status_code == 401


def test_calling_enrol_again_does_NOT_replace_a_CONFIRMED_secret(owner):
    """The other half, and the one that matters: if enrol overwrote a confirmed
    secret, anyone holding a stolen password could simply enrol their own phone. The
    only route back to enrolment is a recovery code."""
    from apps.accounts.models import StaffTOTP
    from apps.accounts.totp import decrypt_secret

    secret, _data = full_ceremony(owner)
    preauth = preauth_for(owner)
    r = bearer(preauth).post(ENROL, {}, format="json")
    assert r.status_code == 409, r.data
    assert decrypt_secret(StaffTOTP.objects.get(user=owner).secret_ciphertext) == secret


def test_an_unconfirmed_enrolment_is_inert_in_both_directions(owner):
    """`confirmed_at` is the only thing that counts. An account with a secret it never
    confirmed is treated exactly like one with no secret at all — it still gets a
    preauth token from the password step (so a half-enrolment cannot lock anyone out)
    and it still has no admin session."""
    preauth = preauth_for(owner)
    enrol(preauth)

    r = APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    assert r.status_code == 200
    assert r.data["totp_enrolled"] is False
    assert "access" not in r.data


# --- who may reach the three endpoints ----------------------------------------


@pytest.mark.parametrize("path", PREAUTH_ENDPOINTS)
def test_the_totp_endpoints_refuse_an_anonymous_caller(path):
    assert APIClient().post(path, {}, format="json").status_code == 401


@pytest.mark.parametrize("path", PREAUTH_ENDPOINTS)
def test_the_totp_endpoints_refuse_a_customer_token(customer, path):
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(customer).access_token
    assert bearer(token).post(path, {}, format="json").status_code == 401


@pytest.mark.parametrize("path", PREAUTH_ENDPOINTS)
def test_the_totp_endpoints_refuse_a_full_ADMIN_token(owner, path):
    """The two audiences are mutually exclusive by construction. Asserted here because
    the natural mistake — letting an admin token re-enrol — would give anyone holding a
    stolen session a way to move the second factor onto their own phone."""
    _secret, data = full_ceremony(owner)
    assert bearer(data["access"]).post(path, {}, format="json").status_code == 401


def test_a_preauth_token_reaches_exactly_those_three_endpoints_and_nothing_else(owner):
    """The enumerated set, asserted against the live URLconf rather than against a
    list someone remembered to update. A route added later that accepts the preauth
    class fails `test_admin_surface_guard.py`; a route that stops accepting it fails
    here."""
    from apps.accounts.tests.test_admin_surface_guard import preauth_accepting_paths

    assert preauth_accepting_paths() == {p.lstrip("/") for p in PREAUTH_ENDPOINTS}

    preauth = preauth_for(owner)
    client = bearer(preauth)
    assert client.get(ADMIN_ME).status_code == 401
    assert client.get("/api/v1/admin/orders/").status_code == 401
    assert client.get("/api/v1/auth/me/").status_code == 401
    assert client.get("/api/v1/me/addresses/").status_code == 401


def test_a_superuser_without_totp_gets_a_preauth_token_and_nothing_more(superuser):
    """PROVING THERE IS NO SUPERUSER GAP. `rbac.scopes_for_user` short-circuits
    superusers to every scope, which is harmless only because scopes are evaluated on
    requests that already carry the admin audience claim — and the claim is minted at
    TOTP-confirm, which has no superuser branch. If one were ever added, this test is
    what fails.
    """
    from apps.accounts.tests.test_admin_surface_guard import preauth_accepting_paths

    r = APIClient().post(ADMIN_TOKEN, {"email": superuser.email, "password": PW}, format="json")
    assert r.status_code == 200
    assert "access" not in r.data and "refresh" not in r.data
    assert r.data["totp_enrolled"] is False

    client = bearer(r.data["preauth_token"])
    assert client.get(ADMIN_ME).status_code == 401
    assert client.get("/api/v1/admin/orders/").status_code == 401
    assert preauth_accepting_paths() == {p.lstrip("/") for p in PREAUTH_ENDPOINTS}


# --- brute force: layer 1, per preauth ----------------------------------------


def test_five_wrong_codes_invalidate_that_preauth_token(owner, clock):
    from apps.accounts.totp import PREAUTH_FAILURE_LIMIT

    assert PREAUTH_FAILURE_LIMIT == 5
    secret, _data = full_ceremony(owner, clock=clock)
    preauth = preauth_for(owner)
    client = bearer(preauth)

    for _ in range(PREAUTH_FAILURE_LIMIT):
        assert client.post(CONFIRM, {"code": "000000"}, format="json").status_code == 401

    # The token itself is dead now — even a CORRECT code cannot revive it.
    clock.advance(60)
    dead = client.post(CONFIRM, {"code": clock.code(secret)}, format="json")
    assert dead.status_code == 401

    # ...and a fresh ceremony still works, so this invalidated one token, not the account.
    assert confirm(preauth_for(owner), secret, clock).status_code == 200


@pytest.mark.parametrize("path", PREAUTH_ENDPOINTS)
def test_a_burned_preauth_token_reaches_none_of_the_three_endpoints(owner, path):
    """Invalidation is checked in the AUTHENTICATION class, not per view, so a preauth
    token that ran out of guesses stops being a credential everywhere at once. A
    per-view check would have to be remembered on the fourth endpoint somebody adds."""
    from apps.accounts.totp import PREAUTH_FAILURE_LIMIT

    preauth = preauth_for(owner)
    client = bearer(preauth)
    enrol(preauth)
    for _ in range(PREAUTH_FAILURE_LIMIT):
        client.post(CONFIRM, {"code": "000000"}, format="json")

    assert client.post(path, {"code": "000000"}, format="json").status_code == 401


def test_burning_one_preauth_token_does_not_burn_another(owner):
    from apps.accounts.totp import PREAUTH_FAILURE_LIMIT

    first = preauth_for(owner)
    second = preauth_for(owner)
    for _ in range(PREAUTH_FAILURE_LIMIT):
        bearer(first).post(CONFIRM, {"code": "000000"}, format="json")

    assert bearer(second).post(ENROL, {}, format="json").status_code == 200


def test_reaching_the_preauth_cap_logs_at_error(owner, caplog):
    with caplog.at_level(logging.INFO, logger="apps.security"):
        preauth = preauth_for(owner)
        for _ in range(5):
            bearer(preauth).post(CONFIRM, {"code": "000000"}, format="json")
    errors = _security_records(caplog, logging.ERROR)
    assert any("preauth" in rec.getMessage() for rec in errors), [
        r.getMessage() for r in errors
    ]


# --- brute force: layer 2, per user, across preauths ---------------------------


def test_twenty_failures_in_an_hour_hard_deny_the_user(owner):
    """The layer that actually caps the attack. Per-preauth invalidation alone is
    beatable for about $46 of solver tokens, because an attacker holding the password
    produces SUCCESSFUL password authentications and the login throttles — which count
    failures — never move. This one is keyed on the user and survives new preauth
    tokens, so the ~46,000 ceremonies become ~480 days."""
    from apps.accounts.totp import USER_FAILURE_LIMIT

    assert USER_FAILURE_LIMIT == 20
    secret, _data = full_ceremony(owner)

    for _ in range(USER_FAILURE_LIMIT // 4):
        preauth = preauth_for(owner)  # a fresh preauth every four guesses
        for _ in range(4):
            bearer(preauth).post(CONFIRM, {"code": "000000"}, format="json")

    fresh = preauth_for(owner)
    denied = bearer(fresh).post(
        CONFIRM, {"code": code_for(secret, int(time.time()) + 60)}, format="json"
    )
    assert denied.status_code == 429, denied.data


def test_the_user_cap_alert_says_the_password_is_compromised(owner, caplog):
    """The lockout objection does not apply to this cap, and the alert has to say so:
    only someone who already holds the staff password can burn this bucket, so the
    operator's first action is to rotate the password, not to clear the bucket."""
    from apps.accounts.totp import USER_FAILURE_LIMIT

    with caplog.at_level(logging.INFO, logger="apps.security"):
        for _ in range(USER_FAILURE_LIMIT // 4):
            preauth = preauth_for(owner)
            for _ in range(4):
                bearer(preauth).post(CONFIRM, {"code": "000000"}, format="json")

    errors = _security_records(caplog, logging.ERROR)
    text = " | ".join(rec.getMessage() for rec in errors)
    assert "TOTP brute force" in text, text
    assert "password" in text and "rotate" in text, text


def test_the_user_cap_denies_every_totp_endpoint_not_just_confirm(owner):
    from apps.accounts.totp import USER_FAILURE_LIMIT

    for _ in range(USER_FAILURE_LIMIT // 4):
        preauth = preauth_for(owner)
        for _ in range(4):
            bearer(preauth).post(CONFIRM, {"code": "000000"}, format="json")

    fresh = preauth_for(owner)
    assert bearer(fresh).post(ENROL, {}, format="json").status_code == 429
    assert bearer(fresh).post(RECOVERY, {"code": "x" * 20}, format="json").status_code == 429


def test_a_successful_verification_resets_both_counters(owner, clock):
    """Otherwise a staff member who fumbles the code nineteen times over a morning is
    one typo away from an hour's lockout, having proved who they are in between."""
    from apps.accounts.totp import user_failure_count

    secret, _data = full_ceremony(owner, clock=clock)

    preauth = preauth_for(owner)
    for _ in range(4):
        bearer(preauth).post(CONFIRM, {"code": "000000"}, format="json")
    assert user_failure_count(owner) == 4

    clock.advance(60)
    ok = confirm(preauth, secret, clock)
    assert ok.status_code == 200, ok.data
    assert user_failure_count(owner) == 0

    # The preauth counter is cleared too: four MORE wrong codes on the same token do
    # not burn it, which they would if the count had merely stopped at four.
    for _ in range(4):
        assert bearer(preauth).post(
            CONFIRM, {"code": "000000"}, format="json"
        ).status_code == 401
    clock.advance(60)
    assert confirm(preauth, secret, clock).status_code == 200


# --- recovery codes -----------------------------------------------------------


def test_a_recovery_code_is_single_use(owner):
    _secret, data = full_ceremony(owner)
    code = data["recovery_codes"][0]

    preauth = preauth_for(owner)
    first = bearer(preauth).post(RECOVERY, {"code": code}, format="json")
    assert first.status_code == 200, first.data

    again = bearer(preauth_for(owner)).post(RECOVERY, {"code": code}, format="json")
    assert again.status_code == 401


def test_consuming_a_recovery_code_mints_no_admin_token(owner):
    """The rule "only TOTP-confirm mints" has zero exceptions, and this is where the
    convenience argument for an exception is strongest. Paying the extra round trip
    keeps the invariant literal, which is worth more than saving a screen."""
    _secret, data = full_ceremony(owner)
    preauth = preauth_for(owner)
    r = bearer(preauth).post(RECOVERY, {"code": data["recovery_codes"][0]}, format="json")

    assert r.status_code == 200
    assert "access" not in r.data and "refresh" not in r.data
    assert r.data["enrolment_required"] is True


def test_consuming_a_recovery_code_voids_the_secret_and_the_remaining_codes(owner):
    """A recovery code is used because a device is GONE. The old secret is on that
    device and the remaining printed codes were in the same drawer, so both are treated
    as lost."""
    from apps.accounts.models import StaffRecoveryCode, StaffTOTP

    secret, data = full_ceremony(owner)
    codes = data["recovery_codes"]

    preauth = preauth_for(owner)
    bearer(preauth).post(RECOVERY, {"code": codes[0]}, format="json")

    assert not StaffTOTP.objects.filter(user=owner).exists()
    assert StaffRecoveryCode.objects.filter(user=owner, used_at__isnull=True).count() == 0

    # THE ASSERTION THAT FOUND THE BUG. Clearing `confirmed_at` and leaving the
    # ciphertext behind looked correct and was not: TOTP confirm verifies against
    # whatever secret is stored, so the lost phone's authenticator app simply
    # re-confirmed the enrolment and minted an admin session. Asserting against the old
    # APP rather than against the column is what caught it.
    assert bearer(preauth).post(CONFIRM, {"code": code_for(secret)}, format="json").status_code == 401
    # ...and so is every other code from the same set.
    assert bearer(preauth).post(RECOVERY, {"code": codes[1]}, format="json").status_code == 401


def test_recovery_returns_the_user_to_enrol_and_a_new_code_set_issues(owner):
    _secret, data = full_ceremony(owner)
    preauth = preauth_for(owner)
    bearer(preauth).post(RECOVERY, {"code": data["recovery_codes"][0]}, format="json")

    fresh_secret = enrol(preauth)["secret"]
    r = confirm(preauth, fresh_secret)
    assert r.status_code == 200, r.data
    assert len(r.data["recovery_codes"]) == 8
    assert set(r.data["recovery_codes"]).isdisjoint(data["recovery_codes"])
    assert bearer(r.data["access"]).get(ADMIN_ME).status_code == 200


def test_recovery_codes_are_stored_as_digests_only(owner):
    from apps.accounts.models import StaffRecoveryCode

    _secret, data = full_ceremony(owner)
    stored = set(StaffRecoveryCode.objects.values_list("code_hash", flat=True))
    assert stored.isdisjoint(data["recovery_codes"])
    assert stored == {
        hashlib.sha256(c.encode()).hexdigest() for c in data["recovery_codes"]
    }


def test_using_a_recovery_code_logs_at_error(owner, caplog):
    """ERROR, i.e. a Sentry event. A device is gone; that is an event, not a
    breadcrumb — and it is also exactly what an attacker who stole a password and a
    printed code sheet would do."""
    _secret, data = full_ceremony(owner)
    with caplog.at_level(logging.INFO, logger="apps.security"):
        bearer(preauth_for(owner)).post(
            RECOVERY, {"code": data["recovery_codes"][0]}, format="json"
        )
    errors = _security_records(caplog, logging.ERROR)
    assert any("recovery code" in rec.getMessage() for rec in errors)


def test_a_recovery_code_needs_a_preauth_token_first(owner, customer):
    """Bypass scope is the TOTP FACTOR only, never the ceremony. There is no bare
    recovery-to-session path: password and Turnstile always came first, so a leaked
    code sheet on its own is worth nothing."""
    _secret, data = full_ceremony(owner)
    code = data["recovery_codes"][0]

    assert APIClient().post(RECOVERY, {"code": code}, format="json").status_code == 401

    from rest_framework_simplejwt.tokens import RefreshToken

    customer_token = RefreshToken.for_user(customer).access_token
    assert bearer(customer_token).post(RECOVERY, {"code": code}, format="json").status_code == 401


def test_one_users_recovery_code_does_not_work_for_another(owner, django_user_model):
    other = django_user_model.objects.create_user(
        email="other@toke.test", password=PW, is_staff=True
    )
    other.groups.add(Group.objects.get(name="Support"))
    _secret, data = full_ceremony(owner)

    r = bearer(preauth_for(other)).post(
        RECOVERY, {"code": data["recovery_codes"][0]}, format="json"
    )
    assert r.status_code == 401


# --- lifecycle logging --------------------------------------------------------


def test_enrolment_and_confirmation_are_logged(owner, caplog):
    with caplog.at_level(logging.INFO, logger="apps.security"):
        full_ceremony(owner)
    messages = [rec.getMessage() for rec in _security_records(caplog)]
    assert any("TOTP enrolment started" in m for m in messages), messages
    assert any("TOTP enrolment confirmed" in m for m in messages), messages


def test_the_secret_and_the_provisioning_uri_are_never_logged(owner, caplog):
    with caplog.at_level(logging.DEBUG):
        secret, data = full_ceremony(owner)
    blob = "\n".join(rec.getMessage() for rec in caplog.records)
    assert secret not in blob
    assert "otpauth://" not in blob
    for code in data["recovery_codes"]:
        assert code not in blob


def test_a_wrong_code_is_a_warning_not_an_event(owner, caplog):
    """A fat-fingered code is the single most common thing this endpoint sees. At ERROR
    it would raise a Sentry event per typo and train whoever reads them to dismiss the
    stream — which is where the two cap alerts live."""
    full_ceremony(owner)
    with caplog.at_level(logging.INFO, logger="apps.security"):
        caplog.clear()
        bearer(preauth_for(owner)).post(CONFIRM, {"code": "000000"}, format="json")
    records = _security_records(caplog)
    assert any(
        rec.levelno == logging.WARNING and "TOTP code rejected" in rec.getMessage()
        for rec in records
    ), [(r.levelname, r.getMessage()) for r in records]
    assert not _security_records(caplog, logging.ERROR)


# --- the management commands the runbook promises ------------------------------


def test_reset_staff_totp_clears_the_enrolment_and_the_codes(owner):
    from django.core.management import call_command

    from apps.accounts.models import StaffRecoveryCode, StaffTOTP

    full_ceremony(owner)
    call_command("reset_staff_totp", owner.email)

    assert not StaffTOTP.objects.filter(user=owner).exists()
    assert not StaffRecoveryCode.objects.filter(user=owner).exists()

    r = APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    assert r.data["totp_enrolled"] is False
    assert enrol(r.data["preauth_token"])["secret"]


def test_reset_staff_totp_refuses_an_unknown_address():
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("reset_staff_totp", "nobody@toke.test")


def test_reset_staff_totp_logs_at_error(owner, caplog):
    from django.core.management import call_command

    full_ceremony(owner)
    with caplog.at_level(logging.INFO, logger="apps.security"):
        call_command("reset_staff_totp", owner.email)
    assert any(
        rec.levelno == logging.ERROR and "TOTP reset" in rec.getMessage()
        for rec in _security_records(caplog, logging.ERROR)
    )


# --- the caps are cache-backed; make that explicit -----------------------------


def test_clearing_the_cache_lifts_the_user_lock(owner):
    """Documented so the runbook's break-glass is a tested claim rather than a hope:
    the per-user lock lives in the cache (Redis in production), so the operator remedy
    is a key delete — and it is the LAST resort, because burning that bucket requires
    the staff password."""
    from apps.accounts.totp import USER_FAILURE_LIMIT, user_is_locked

    for _ in range(USER_FAILURE_LIMIT // 4):
        preauth = preauth_for(owner)
        for _ in range(4):
            bearer(preauth).post(CONFIRM, {"code": "000000"}, format="json")
    assert user_is_locked(owner)

    cache.clear()
    assert not user_is_locked(owner)


# --- the race ------------------------------------------------------------------


class RecoveryCodeRaceTest(TransactionTestCase):
    """Single-use has to survive two submissions arriving at once.

    Check-then-set loses this race: both requests read `used_at IS NULL`, both proceed,
    and one recovery code re-enrols two devices. The consume is therefore ONE
    conditional UPDATE — the database evaluates the predicate while holding the row
    lock, so exactly one call sees a rowcount of 1. Same discipline, same shape and the
    same two-thread proof as `test_staff_invites.AcceptRaceTest`; reusing a proven
    pattern rather than inventing a second one is the point.

    `TransactionTestCase` rather than the usual pytest-django harness because the
    default wraps each test in a transaction that never commits, which would hide the
    race entirely — both threads would sit inside the same outer transaction and the
    second would simply not see the row.
    """

    serialized_rollback = True  # restore the migration-seeded role groups after the flush

    def test_two_concurrent_uses_of_one_recovery_code_yield_exactly_one_winner(self):
        from django.contrib.auth import get_user_model
        from django.db import connections

        from apps.accounts.totp import consume_recovery_code, issue_recovery_codes

        User = get_user_model()
        staff = User.objects.create_user(email="race@toke.test", password=PW, is_staff=True)
        staff.groups.add(Group.objects.get(name="Support"))
        code = issue_recovery_codes(staff)[0]

        results = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait(timeout=5)
                results.append(consume_recovery_code(staff, code))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert sorted(results) == [False, True], results
