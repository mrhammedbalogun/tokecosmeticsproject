"""Staff authentication: `/auth/admin-token/` and `/auth/admin-me/`.

Four properties are load-bearing here and each has a test that fails loudly:

0. **A customer-issued token cannot open an admin endpoint.** The two endpoints used
   to mint indistinguishable tokens, so every protection on `admin-token/` was
   bypassable by logging a staff account in at `/auth/token/` instead. Admin refresh
   tokens now carry an audience claim, and the admin authentication class refuses
   anything without it.


1. **A customer account cannot become a staff session.** The staff check lives in
   the serializer and returns the SAME body as bad credentials, so the endpoint
   never confirms "that address is real, just not staff" — which would hand an
   attacker a list of accounts worth phishing.
2. **The gate is Turnstile'd** (Plan-16 Amendment 1: the endpoint is publicly
   reachable, so exempting it left the higher-value login with less protection
   than customer login has). `TURNSTILE_ADMIN_SECRET` overrides `TURNSTILE_SECRET`
   for this endpoint only.
3. **Password spraying is metered by IP.** This is the regression that bit
   customer login before `LoginIPThrottle` existed: per-email counters alone leave
   one-guess-per-address entirely unmetered.

conftest.py force-disables Turnstile for the whole suite, so the tests here that
exercise the gate switch it on explicitly (same pattern as test_turnstile.py).

TASK 3b CHANGED WHAT `/auth/admin-token/` RETURNS. It is now step ONE of three and
mints nothing: a correct staff password yields a ten-minute PREAUTH token, and the
admin token pair comes only from TOTP confirm. Every test here that needs a real admin
session therefore runs the whole ceremony through `admin_session()` below rather than
reading `response.data["access"]`. The ceremony itself — drift, replay, the two
brute-force caps, recovery codes — belongs to `test_staff_totp.py`; this file still owns
the password step, the Turnstile gate, the throttles, and what an admin-audience token
may do once it exists.
"""
import logging

import httpx
import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from apps.accounts.tests.test_staff_totp import full_ceremony

pytestmark = pytest.mark.django_db

PW = "Str0ng!pass9"
ADMIN_TOKEN = "/api/v1/auth/admin-token/"
ADMIN_ME = "/api/v1/auth/admin-me/"
CUSTOMER_TOKEN = "/api/v1/auth/token/"


@pytest.fixture
def owner(django_user_model):
    user = django_user_model.objects.create_user(
        email="owner@toke.test", password=PW, is_staff=True, first_name="Toke", last_name="Owner"
    )
    user.groups.add(Group.objects.get(name="Owner"))
    return user


@pytest.fixture
def support(django_user_model):
    user = django_user_model.objects.create_user(
        email="support@toke.test", password=PW, is_staff=True
    )
    user.groups.add(Group.objects.get(name="Support"))
    return user


@pytest.fixture
def customer(django_user_model):
    return django_user_model.objects.create_user(email="shopper@toke.test", password=PW)


class _Recorder:
    """Stands in for httpx.post; records the outgoing call, returns a canned reply."""

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


def admin_session(user, password=PW) -> dict:
    """The full ceremony: password -> preauth -> TOTP enrol -> TOTP confirm.

    Returns the confirm response, which is the only place in the project an
    admin-audience token pair comes from.
    """
    _secret, data = full_ceremony(user, password)
    return data


# --- staff-only, and silent about why -----------------------------------------


def test_staff_password_yields_a_preauth_token_and_no_session(owner):
    """THE TASK 3b CHANGE, pinned. This endpoint used to answer a correct staff password
    with a full admin session — which meant the `toke-admin` claim actually meant
    "password", and the preauth token accept-invite returned was a fence around a door
    that was still open. It now mints nothing at all."""
    r = APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    assert r.status_code == 200
    assert "access" not in r.data and "refresh" not in r.data
    assert r.data["preauth_token"]


def test_customer_with_correct_credentials_is_rejected(customer):
    r = APIClient().post(ADMIN_TOKEN, {"email": customer.email, "password": PW}, format="json")
    assert r.status_code == 401


def test_customer_rejection_is_indistinguishable_from_a_bad_password(customer, owner):
    """Any difference here is an oracle: it tells an attacker which of the addresses
    they hold is a real account, and separately which is a real STAFF account."""
    client = APIClient()
    real_customer = client.post(
        ADMIN_TOKEN, {"email": customer.email, "password": PW}, format="json"
    )
    wrong_password = client.post(
        ADMIN_TOKEN, {"email": owner.email, "password": "nope"}, format="json"
    )
    no_such_account = client.post(
        ADMIN_TOKEN, {"email": "ghost@toke.test", "password": PW}, format="json"
    )

    assert real_customer.status_code == wrong_password.status_code == no_such_account.status_code
    assert real_customer.json() == wrong_password.json() == no_such_account.json()


def test_rejecting_a_customer_mints_no_token(customer):
    """The staff check runs BEFORE the refresh token is created, so a rejected login
    leaves no OutstandingToken row — no unusable-but-valid token sitting in the DB."""
    from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

    APIClient().post(ADMIN_TOKEN, {"email": customer.email, "password": PW}, format="json")
    assert OutstandingToken.objects.filter(user=customer).count() == 0


def test_customer_login_endpoint_still_accepts_customers(customer):
    """admin-token is an ADDITION; /auth/token/ stays customer-shaped."""
    r = APIClient().post(CUSTOMER_TOKEN, {"email": customer.email, "password": PW}, format="json")
    assert r.status_code == 200


# --- the admin audience claim --------------------------------------------------


def _claim_of(raw_access):
    from rest_framework_simplejwt.tokens import AccessToken

    from apps.accounts.authentication import ADMIN_AUDIENCE, ADMIN_AUDIENCE_CLAIM

    return AccessToken(raw_access).get(ADMIN_AUDIENCE_CLAIM), ADMIN_AUDIENCE


def test_a_completed_ceremony_carries_the_audience_claim(owner):
    claim, expected = _claim_of(admin_session(owner)["access"])
    assert claim == expected


def test_customer_token_does_not_carry_the_audience_claim(customer):
    r = APIClient().post(CUSTOMER_TOKEN, {"email": customer.email, "password": PW}, format="json")
    claim, _expected = _claim_of(r.data["access"])
    assert claim is None


def test_a_staff_token_from_the_customer_endpoint_cannot_open_admin_me(owner):
    """THE REGRESSION. Before the audience claim this returned 200: the two endpoints
    minted identical tokens, so an attacker could ignore admin-token's Turnstile gate
    and 5/min throttle entirely and brute-force the staff password at the customer
    door instead. The claim is what makes the resulting token useless."""
    client = APIClient()
    login = client.post(CUSTOMER_TOKEN, {"email": owner.email, "password": PW}, format="json")
    assert login.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    assert client.get(ADMIN_ME).status_code == 401


def test_a_refreshed_admin_token_still_carries_the_claim(owner):
    """SimpleJWT copies every claim from a refresh token to the access tokens it
    mints, minus its `no_copy_claims` denylist, so the SHARED /auth/token/refresh/
    endpoint needs no admin-specific code. If that ever stops being true, an admin
    session would silently die 15 minutes after login."""
    client = APIClient()
    login = admin_session(owner)

    refreshed = client.post(
        "/api/v1/auth/token/refresh/", {"refresh": login["refresh"]}, format="json"
    )
    assert refreshed.status_code == 200
    claim, expected = _claim_of(refreshed.data["access"])
    assert claim == expected

    # Rotation issues a NEW refresh token too; it must carry the claim as well, or
    # the session dies at the second renewal instead of the first.
    again = client.post(
        "/api/v1/auth/token/refresh/", {"refresh": refreshed.data["refresh"]}, format="json"
    )
    assert again.status_code == 200
    claim, expected = _claim_of(again.data["access"])
    assert claim == expected

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {again.data['access']}")
    assert client.get(ADMIN_ME).status_code == 200


def test_a_refreshed_customer_token_never_grows_the_claim(customer):
    """The claim can only be minted by admin-token/, so refreshing cannot launder a
    customer token into an admin one."""
    client = APIClient()
    login = client.post(CUSTOMER_TOKEN, {"email": customer.email, "password": PW}, format="json")
    refreshed = client.post(
        "/api/v1/auth/token/refresh/", {"refresh": login.data["refresh"]}, format="json"
    )
    claim, _expected = _claim_of(refreshed.data["access"])
    assert claim is None


# --- Turnstile -----------------------------------------------------------------


def test_gate_is_a_noop_while_no_secret_is_set(owner, monkeypatch):
    recorder = _siteverify(monkeypatch)
    r = APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    assert r.status_code == 200
    assert recorder.calls == []


def test_customer_secret_alone_gates_admin_login(settings, owner, monkeypatch):
    settings.TURNSTILE_SECRET = "sk-customer"
    _siteverify(monkeypatch)
    client = APIClient()
    assert client.post(
        ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json"
    ).status_code == 403
    assert client.post(
        ADMIN_TOKEN,
        {"email": owner.email, "password": PW, "turnstile_token": "tok"},
        format="json",
    ).status_code == 200


def test_admin_secret_alone_gates_admin_login(settings, owner, monkeypatch):
    """The admin app is a new hostname and Turnstile widgets are domain-scoped, so the
    admin gate must be able to run on its own widget/secret."""
    settings.TURNSTILE_SECRET = ""
    settings.TURNSTILE_ADMIN_SECRET = "sk-admin"
    recorder = _siteverify(monkeypatch)
    r = APIClient().post(
        ADMIN_TOKEN,
        {"email": owner.email, "password": PW, "turnstile_token": "tok"},
        format="json",
    )
    assert r.status_code == 200
    assert recorder.calls[0]["data"] == {"secret": "sk-admin", "response": "tok"}


def test_admin_secret_takes_precedence_over_the_customer_secret(settings, owner, monkeypatch):
    settings.TURNSTILE_SECRET = "sk-customer"
    settings.TURNSTILE_ADMIN_SECRET = "sk-admin"
    recorder = _siteverify(monkeypatch)
    r = APIClient().post(
        ADMIN_TOKEN,
        {"email": owner.email, "password": PW, "turnstile_token": "tok"},
        format="json",
    )
    assert r.status_code == 200
    assert recorder.calls[0]["data"]["secret"] == "sk-admin"


def test_admin_secret_does_not_gate_customer_login(settings, customer, monkeypatch):
    """Break-glass in one direction only: dropping TURNSTILE_ADMIN_SECRET must not be
    able to open the customer gate, and setting it must not close it either."""
    settings.TURNSTILE_SECRET = ""
    settings.TURNSTILE_ADMIN_SECRET = "sk-admin"
    _siteverify(monkeypatch)
    r = APIClient().post(CUSTOMER_TOKEN, {"email": customer.email, "password": PW}, format="json")
    assert r.status_code == 200


def test_a_rejected_turnstile_token_blocks_admin_login(settings, owner, monkeypatch):
    settings.TURNSTILE_ADMIN_SECRET = "sk-admin"
    _siteverify(monkeypatch, success=False)
    r = APIClient().post(
        ADMIN_TOKEN,
        {"email": owner.email, "password": PW, "turnstile_token": "tok"},
        format="json",
    )
    assert r.status_code == 403


# --- throttling ----------------------------------------------------------------


def test_ip_throttle_is_listed_first():
    """Order matters: the IP throttle must record before the email throttle reads
    request.data, which can raise ParseError on a malformed body."""
    from apps.accounts.throttling import AdminLoginIPThrottle
    from apps.accounts.views import AdminLoginView

    assert AdminLoginView.throttle_classes[0] is AdminLoginIPThrottle


def test_admin_rates_are_stricter_than_the_customer_ones():
    """Staff login volume is ~zero, so these are deliberately tighter than the
    storefront's. Pinned because they are a security parameter, not a tuning knob.

    The literals are pinned AND compared. The comparison is the part that has teeth:
    the previous version of this test asserted only the two literals and never read a
    customer rate, so loosening `login_burst` to `1/min` — making the customer gate
    STRICTER than the admin one, which is the exact inversion the name warns about —
    left it green.
    """
    from rest_framework.throttling import SimpleRateThrottle

    from apps.accounts.throttling import AdminLoginEmailThrottle, AdminLoginIPThrottle

    rates = AdminLoginIPThrottle.THROTTLE_RATES
    assert rates["admin_login_ip"] == "5/min"
    assert AdminLoginEmailThrottle.THROTTLE_RATES["admin_login_email"] == "10/hour"

    def per_second(rate: str) -> float:
        """Requests/second, so `10/hour` and `5/min` are actually comparable.

        DRF's own parser, called unbound: it never touches `self`, and instantiating
        `SimpleRateThrottle` raises because it has no scope.
        """
        num, duration = SimpleRateThrottle.parse_rate(None, rate)
        return num / duration

    assert per_second(rates["admin_login_ip"]) < per_second(rates["login_ip"]), (
        "the admin volume cap must be tighter than the storefront's"
    )
    for customer_scope in ("login_burst", "login_sustained"):
        assert per_second(rates["admin_login_email"]) < per_second(rates[customer_scope]), (
            f"admin_login_email must be tighter than {customer_scope}"
        )


def test_password_spraying_across_many_emails_is_capped(client):
    """The regression that bit customer login: one guess each against many addresses
    touches no per-email counter, so without an IP key it is entirely unmetered."""
    codes = [
        client.post(
            ADMIN_TOKEN,
            {"email": f"spray-{i}@toke.test", "password": "Password123!"},
            content_type="application/json",
        ).status_code
        for i in range(8)
    ]
    assert 429 in codes, "admin login accepted unmetered password spraying"
    assert codes.index(429) <= 5, f"admin_login_ip is 5/min; first 429 at {codes.index(429) + 1}"


def test_one_account_is_capped_across_rotating_ips(client, owner):
    """The email key is the one an attacker cannot rotate away from — it is read from
    the body, not from a header any proxy hop can rewrite."""
    codes = [
        client.post(
            ADMIN_TOKEN,
            {"email": owner.email, "password": f"guess-{i}"},
            content_type="application/json",
            HTTP_CF_CONNECTING_IP=f"198.51.100.{i}",
        ).status_code
        for i in range(12)
    ]
    assert 429 in codes, "guesses against one staff account were not capped across IPs"


# --- the shared-egress lockout ------------------------------------------------
# Every one of these is the SAME bug in a different costume: `admin_login_ip` is one
# bucket shared by the entire staff, because the admin BFF calls this endpoint
# server-side from Vercel (Task 5 — the storefront's `lib/auth-session.ts` is the
# pattern being copied). Anything an anonymous stranger can put in that bucket
# without spending a password guess is a free, total, indefinite staff lockout.


def test_bodyless_junk_cannot_lock_staff_out_of_their_own_admin(client, owner):
    """THE LOCKOUT, in its cheapest form. Five EMPTY JSON POSTs a minute — no
    Turnstile solved, no password guessed, no victim address needed, nothing that
    even resembles a credential — used to fill `admin_login_ip` and 429 every staff
    login for as long as the attacker cared to keep going.

    `check_throttles()` runs in `initial()`, i.e. before `require_turnstile`, so the
    Turnstile gate being ON in production does not blunt this at all: the junk is
    counted before it is refused.
    """
    for _ in range(5):  # the whole 5/min allowance, spent on nothing
        client.post(ADMIN_TOKEN, {}, content_type="application/json")

    r = client.post(
        ADMIN_TOKEN, {"email": owner.email, "password": PW}, content_type="application/json"
    )
    assert r.status_code == 200, (
        "an anonymous party denied staff access to their own admin at zero cost"
    )


def test_turnstile_rejections_do_not_consume_the_ip_bucket(
    settings, owner, monkeypatch, client
):
    """The IP-key twin of the email-bucket test below, and the reason the same
    reasoning has to apply to both keys: a bot that never cleared the human check has
    not made a credential attempt, so it must not be able to spend the staff's
    allowance. Otherwise the gate being on merely puts a price on the lockout instead
    of preventing it."""
    settings.TURNSTILE_ADMIN_SECRET = "sk-admin"
    _siteverify(monkeypatch, success=True)

    for _ in range(5):
        r = client.post(
            ADMIN_TOKEN,
            {"email": "nobody@toke.test", "password": "x"},  # no turnstile_token
            content_type="application/json",
        )
        assert r.status_code == 403

    good = client.post(
        ADMIN_TOKEN,
        {"email": owner.email, "password": PW, "turnstile_token": "tok"},
        content_type="application/json",
    )
    assert good.status_code == 200, "Turnstile-blocked junk locked the staff out"


def test_a_malformed_body_consumes_neither_bucket(client, owner):
    """Pins the claim `LoginIPThrottle`'s docstring makes but never tested: a body so
    broken that reading it raises `ParseError` is not a login attempt. It reaches
    neither a Turnstile check nor a password check, so neither counter may move."""
    for _ in range(5):
        r = client.post(ADMIN_TOKEN, "{not json at all", content_type="application/json")
        assert r.status_code == 400

    ok = client.post(
        ADMIN_TOKEN, {"email": owner.email, "password": PW}, content_type="application/json"
    )
    assert ok.status_code == 200, "a malformed body consumed the staff's login allowance"


def test_a_successful_login_clears_the_ip_bucket(client, owner):
    """Reset-on-success is what makes the shared bucket survivable, and it is safe
    precisely BECAUSE the bucket is shared: only a real staff member can produce a
    successful login, so the reset reaches the Vercel egress address the staff share
    and never an attacker's own address, where no login will ever succeed."""

    def fail_four_times():
        return [
            client.post(
                ADMIN_TOKEN,
                {"email": f"guess-{i}@toke.test", "password": "Password123!"},
                content_type="application/json",
            ).status_code
            for i in range(4)
        ]

    assert 429 not in fail_four_times()  # four failures, allowance is five
    ok = client.post(
        ADMIN_TOKEN, {"email": owner.email, "password": PW}, content_type="application/json"
    )
    assert ok.status_code == 200
    assert 429 not in fail_four_times(), "a proven staff login did not clear the IP bucket"


def test_turnstile_rejections_do_not_consume_the_email_bucket(
    settings, owner, monkeypatch, client
):
    """THE LOCKOUT FIX. When the email bucket counted REQUESTS, ten anonymous junk
    POSTs carrying the owner's address locked him out of his own store for an hour,
    at zero cost to the attacker and recoverable only by SSHing in to clear Redis.

    Counting only failed CREDENTIALS means a request that never got as far as a
    password check cannot lock anyone out — and once the Turnstile gate is on, every
    countable failure costs the attacker a solved token.
    """
    settings.TURNSTILE_ADMIN_SECRET = "sk-admin"
    _siteverify(monkeypatch, success=True)

    for i in range(12):  # 12 > the 10/hour email allowance
        r = client.post(
            ADMIN_TOKEN,
            {"email": owner.email, "password": PW},  # no turnstile_token
            content_type="application/json",
            HTTP_CF_CONNECTING_IP=f"203.0.113.{i}",  # dodge the IP volume cap
        )
        assert r.status_code == 403

    good = client.post(
        ADMIN_TOKEN,
        {"email": owner.email, "password": PW, "turnstile_token": "tok"},
        content_type="application/json",
        HTTP_CF_CONNECTING_IP="203.0.113.200",
    )
    assert good.status_code == 200, "junk that failed Turnstile locked a staff account out"


def test_a_successful_login_resets_the_email_bucket(client, owner):
    """Otherwise a staff member who fumbles their password nine times in the morning
    is one typo away from being locked out all afternoon, despite having proved who
    they are in between."""

    def fail_nine_times():
        return [
            client.post(
                ADMIN_TOKEN,
                {"email": owner.email, "password": f"guess-{i}"},
                content_type="application/json",
                HTTP_CF_CONNECTING_IP=f"198.51.100.{i}",  # dodge the IP volume cap
            ).status_code
            for i in range(9)
        ]

    assert 429 not in fail_nine_times()  # nine failures, allowance is ten

    ok = client.post(
        ADMIN_TOKEN,
        {"email": owner.email, "password": PW},
        content_type="application/json",
        HTTP_CF_CONNECTING_IP="198.51.100.200",
    )
    assert ok.status_code == 200

    # Without the reset the tenth cumulative failure would 429 immediately.
    assert 429 not in fail_nine_times(), "a proven login did not clear the failure count"


def test_admin_throttling_does_not_lock_out_customer_login(client, customer):
    """Separate scopes, separate buckets: an attack on the admin gate must not take
    the storefront's login down with it."""
    for i in range(8):
        client.post(
            ADMIN_TOKEN,
            {"email": f"spray-{i}@toke.test", "password": "x"},
            content_type="application/json",
        )
    r = client.post(
        CUSTOMER_TOKEN,
        {"email": customer.email, "password": PW},
        content_type="application/json",
    )
    assert r.status_code == 200


# --- security logging ----------------------------------------------------------


def test_failed_admin_login_logs_at_error_so_sentry_raises_an_event(customer, caplog):
    """ERROR is the level Sentry's logging integration turns into an EVENT; INFO and
    WARNING only become breadcrumbs. A failed admin login is worth waking someone."""
    with caplog.at_level(logging.INFO, logger="apps.security"):
        r = APIClient().post(
            ADMIN_TOKEN, {"email": customer.email, "password": PW}, format="json"
        )
    assert r.status_code == 401
    errors = [
        rec
        for rec in caplog.records
        if rec.name == "apps.security" and rec.levelno == logging.ERROR
    ]
    assert errors, "a failed admin login must leave an ERROR-level security line"
    assert any("admin login failed" in rec.getMessage() for rec in errors)
    assert any(customer.email in rec.getMessage() for rec in errors)


def test_failed_admin_login_logs_exactly_one_error_record(owner, caplog):
    """The user_login_failed signal ALSO logs this attempt (at WARNING, from
    signals.py). That is fine — a breadcrumb, not a second event — but there must be
    exactly one ERROR record, or one spray becomes a wall of duplicate Sentry issues."""
    with caplog.at_level(logging.INFO, logger="apps.security"):
        APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": "nope"}, format="json")
    errors = [
        rec
        for rec in caplog.records
        if rec.name == "apps.security" and rec.levelno == logging.ERROR
    ]
    assert len(errors) == 1


def _security_errors(caplog):
    return [
        rec
        for rec in caplog.records
        if rec.name == "apps.security" and rec.levelno == logging.ERROR
    ]


def test_hitting_the_admin_rate_limit_logs_at_error_so_sentry_raises_an_event(
    client, caplog
):
    """The loudest signal this gate can produce is someone actually reaching the cap,
    and it was the one that never alerted. `Throttled` is raised in `initial()`, before
    `AdminLoginView.post()` runs, so the view's ERROR line never fires and the generic
    handler logged WARNING — a Sentry breadcrumb, attached to no event."""
    with caplog.at_level(logging.INFO, logger="apps.security"):
        codes = [
            client.post(
                ADMIN_TOKEN,
                {"email": f"spray-{i}@toke.test", "password": "Password123!"},
                content_type="application/json",
            ).status_code
            for i in range(8)
        ]
    assert 429 in codes
    throttle_errors = [
        rec for rec in _security_errors(caplog) if "throttled" in rec.getMessage()
    ]
    assert throttle_errors, "reaching the admin login cap raised no Sentry-visible event"


def test_ordinary_customer_rate_limiting_stays_a_breadcrumb(client, customer, caplog):
    """The other half of the same fix, and the reason it is opt-in per view rather
    than a blanket promotion of 429s: customer throttling is routine and expected —
    promoting it to ERROR would bury the admin signal under storefront noise, which
    is the same as not having the signal."""
    with caplog.at_level(logging.INFO, logger="apps.security"):
        codes = [
            client.post(
                CUSTOMER_TOKEN,
                {"email": customer.email, "password": f"guess-{i}"},
                content_type="application/json",
            ).status_code
            for i in range(8)
        ]
    assert 429 in codes
    assert not _security_errors(caplog), (
        "ordinary customer rate limiting raised Sentry events"
    )


def test_a_throttled_admin_request_is_logged_once_and_counts_as_no_failure(owner, client, caplog):
    """Two claims about a 429, both previously untested.

    ONE line: the view's own ERROR line and the handler's must not both fire, or a
    single spray becomes two Sentry issues that have to be correlated by hand. They
    cannot, because `Throttled` is raised before `post()` — this pins that.

    NO failure counted: a request that was refused before it reached a password check
    is not a credential guess. Counting it would let an attacker who is already capped
    extend a staff member's lockout for free just by continuing to knock.
    """
    for i in range(5):  # spend the IP allowance on other addresses
        client.post(
            ADMIN_TOKEN,
            {"email": f"spray-{i}@toke.test", "password": "Password123!"},
            content_type="application/json",
        )

    with caplog.at_level(logging.INFO, logger="apps.security"):
        caplog.clear()  # the spray above logged too; only the 429 is under test here
        blocked = client.post(
            ADMIN_TOKEN,
            {"email": owner.email, "password": PW},
            content_type="application/json",
        )
    assert blocked.status_code == 429
    assert len(_security_errors(caplog)) == 1, "one 429 produced more than one event"

    from apps.accounts.throttling import AdminLoginEmailThrottle

    class _SameRequest:
        """Enough of a request for the throttle to derive the same cache key."""

        data = {"email": owner.email}
        META: dict[str, str] = {}

    throttle = AdminLoginEmailThrottle()
    key = throttle.get_cache_key(_SameRequest(), view=None)
    assert throttle.cache.get(key, []) == [], "a 429 was counted against the account"


def test_successful_admin_login_logs_at_info(owner, caplog):
    with caplog.at_level(logging.INFO, logger="apps.security"):
        r = APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    assert r.status_code == 200
    assert any(
        rec.levelno == logging.INFO and "admin login succeeded" in rec.getMessage()
        for rec in caplog.records
    )


def test_a_blocked_turnstile_attempt_is_logged_as_a_failure(settings, owner, caplog):
    """A bot hitting the admin gate is exactly as interesting as a wrong password."""
    settings.TURNSTILE_ADMIN_SECRET = "sk-admin"
    with caplog.at_level(logging.INFO, logger="apps.security"):
        r = APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    assert r.status_code == 403
    assert any(
        rec.levelno == logging.ERROR and "admin login failed" in rec.getMessage()
        for rec in caplog.records
    )


# --- admin-me ------------------------------------------------------------------


def test_admin_me_returns_identity_groups_and_scopes(owner):
    from apps.accounts.tests.test_rbac import OWNER

    client = APIClient()
    client.force_authenticate(owner)
    r = client.get(ADMIN_ME)
    assert r.status_code == 200
    assert r.data["email"] == owner.email
    assert r.data["name"] == "Toke Owner"
    assert r.data["groups"] == ["Owner"]
    assert set(r.data["scopes"]) == OWNER


def test_admin_me_scopes_are_per_role(support):
    from apps.accounts.tests.test_rbac import SUPPORT

    client = APIClient()
    client.force_authenticate(support)
    r = client.get(ADMIN_ME)
    assert r.status_code == 200
    assert set(r.data["scopes"]) == SUPPORT


def test_admin_me_rejects_a_customer_even_past_the_audience_claim(customer):
    """The SECOND fence, in isolation. `force_authenticate` bypasses the
    authentication class entirely, so this exercises the permission layer's live
    `is_staff` read on its own — which is what makes a revoked staff account lose
    access immediately rather than whenever its token happens to expire.

    Read as a security guarantee this test is WEAKER than it looks: bypassing
    authentication means it would still pass if `AdminJWTAuthentication` were deleted.
    That is fine for what it is (a unit test of the permission layer) and is why
    `test_admin_me_rejects_a_customer_over_real_http` exists alongside it."""
    client = APIClient()
    client.force_authenticate(customer)
    assert client.get(ADMIN_ME).status_code == 403


def test_admin_me_rejects_a_customer_over_real_http_at_both_fences(customer):
    """The end-to-end version of the test above, which uses `force_authenticate` and
    therefore never touches `AdminJWTAuthentication` at all.

    IT ASSERTS THE TWO STATUS CODES SEPARATELY, and that is the whole design of the
    test rather than a detail. A customer is refused either way, so "the response was
    a rejection" proves nothing about which fence did the refusing — a version of this
    test that only checked 403 kept passing with `authentication_classes` deleted
    outright, because the project-default `JWTAuthentication` then accepts the token
    and `IsAdminUser` produces the same 403. Verified by mutation.

    401 vs 403 is what separates them:

    * a plain customer token has no `toke_aud`, so AUTHENTICATION refuses it and the
      request is anonymous -> 401. Delete the admin authentication class and this
      becomes 403, because the stock class authenticates it happily.
    * a token carrying the claim on a customer account gets past authentication, so
      the live `is_staff` read is what refuses -> 403. It is minted directly here
      because no endpoint will ever produce that combination; it is the shape a
      demoted staff member's still-valid token has.
    """
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.accounts.authentication import ADMIN_AUDIENCE, ADMIN_AUDIENCE_CLAIM

    client = APIClient()

    plain = RefreshToken.for_user(customer)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plain.access_token}")
    assert client.get(ADMIN_ME).status_code == 401, (
        "a customer token without the audience claim must fail at AUTHENTICATION"
    )

    claimed = RefreshToken.for_user(customer)
    claimed[ADMIN_AUDIENCE_CLAIM] = ADMIN_AUDIENCE
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {claimed.access_token}")
    assert client.get(ADMIN_ME).status_code == 403, (
        "a claim-bearing token on a non-staff account must fail at PERMISSIONS"
    )


def test_only_access_tokens_are_configured_as_authentication_tokens():
    """The setting the test below deliberately breaks. SimpleJWT's default is
    access-only, and nothing in `config/settings/base.py` overrides it — but nothing
    pinned it either, so adding `RefreshToken` to the tuple (a plausible thing to do
    when wiring up a token-verify endpoint) would have been silently accepted."""
    from rest_framework_simplejwt.settings import api_settings
    from rest_framework_simplejwt.tokens import AccessToken

    assert tuple(api_settings.AUTH_TOKEN_CLASSES) == (AccessToken,)


def test_a_raw_refresh_token_is_refused_by_the_admin_class(owner, monkeypatch):
    """Defence in depth behind that setting. The audience claim lives on the REFRESH
    token (access tokens inherit it by copy), so a refresh token presented as a bearer
    credential carries a perfectly valid `toke_aud` — and `AdminJWTAuthentication`
    inherited SimpleJWT's loop over `AUTH_TOKEN_CLASSES` without ever checking
    `token_type`. Measured by monkeypatching the setting to the two-class tuple:
    `/auth/admin-me/` returned 200 for a raw refresh token.

    Refresh tokens are long-lived (30 days) and are handed to the browser, so treating
    one as an access credential is a real privilege upgrade, not a technicality.
    """
    from rest_framework_simplejwt.settings import api_settings
    from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

    # The ceremony runs BEFORE the monkeypatch: it uses preauth tokens, and widening
    # AUTH_TOKEN_CLASSES first would change what is under test into something else.
    login = admin_session(owner)
    monkeypatch.setattr(api_settings, "AUTH_TOKEN_CLASSES", (AccessToken, RefreshToken))

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login['refresh']}")
    assert client.get(ADMIN_ME).status_code == 401

    # The access token from the same login must still work, or the check is just broken.
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login['access']}")
    assert client.get(ADMIN_ME).status_code == 200


def test_admin_me_rejects_a_demoted_staff_member_holding_a_valid_admin_token(owner):
    """Claims outlive revocation: the token still says `toke-admin` after is_staff is
    withdrawn. The DB check is what closes that window."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_session(owner)['access']}")
    assert client.get(ADMIN_ME).status_code == 200

    owner.is_staff = False
    owner.save(update_fields=["is_staff"])
    assert client.get(ADMIN_ME).status_code == 403


def test_admin_me_rejects_anonymous():
    assert APIClient().get(ADMIN_ME).status_code == 401


def test_a_token_from_the_completed_ceremony_works_on_admin_me(owner):
    """End-to-end: the pair minted by TOTP confirm authenticates the admin session."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_session(owner)['access']}")
    r = client.get(ADMIN_ME)
    assert r.status_code == 200
    assert r.data["email"] == owner.email
