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
"""
import logging

import httpx
import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

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


# --- staff-only, and silent about why -----------------------------------------


def test_staff_can_obtain_a_token_pair(owner):
    r = APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    assert r.status_code == 200
    assert "access" in r.data and "refresh" in r.data


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


def test_admin_token_carries_the_audience_claim(owner):
    r = APIClient().post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    claim, expected = _claim_of(r.data["access"])
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
    login = client.post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")

    refreshed = client.post(
        "/api/v1/auth/token/refresh/", {"refresh": login.data["refresh"]}, format="json"
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
    """Staff login volume is ~zero and staff lockout is recoverable with root access,
    so these are deliberately brutal. Pinned because they are a security parameter,
    not a tuning knob."""
    from apps.accounts.throttling import AdminLoginEmailThrottle, AdminLoginIPThrottle

    assert AdminLoginIPThrottle.THROTTLE_RATES["admin_login_ip"] == "5/min"
    assert AdminLoginEmailThrottle.THROTTLE_RATES["admin_login_email"] == "10/hour"


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
    """The SECOND fence. `force_authenticate` bypasses the authentication class
    entirely, so this exercises the permission layer's live `is_staff` read on its
    own — which is what makes a revoked staff account lose access immediately rather
    than whenever its token happens to expire."""
    client = APIClient()
    client.force_authenticate(customer)
    assert client.get(ADMIN_ME).status_code == 403


def test_admin_me_rejects_a_demoted_staff_member_holding_a_valid_admin_token(owner):
    """Claims outlive revocation: the token still says `toke-admin` after is_staff is
    withdrawn. The DB check is what closes that window."""
    client = APIClient()
    login = client.post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    assert client.get(ADMIN_ME).status_code == 200

    owner.is_staff = False
    owner.save(update_fields=["is_staff"])
    assert client.get(ADMIN_ME).status_code == 403


def test_admin_me_rejects_anonymous():
    assert APIClient().get(ADMIN_ME).status_code == 401


def test_a_token_from_admin_token_works_on_admin_me(owner):
    """End-to-end: the pair minted by admin-token authenticates the admin session."""
    client = APIClient()
    login = client.post(ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    r = client.get(ADMIN_ME)
    assert r.status_code == 200
    assert r.data["email"] == owner.email
