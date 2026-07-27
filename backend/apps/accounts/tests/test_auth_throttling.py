"""Throttling on the public auth endpoints.

The headline test is `test_rotating_xff_no_longer_buys_fresh_buckets`: it reproduces
the exact bypass that made this slice launch-blocking. Before the fix it allowed 80 of
80 password guesses; it must never pass again.
"""

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.accounts.throttling import _EmailKeyedThrottle, client_ip


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Throttle counters live in the cache and would otherwise leak between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def login_url():
    return reverse("token_obtain_pair")


@pytest.fixture
def register_url():
    return reverse("register")


@pytest.fixture
def reset_url():
    return reverse("password_reset")


# --- the bypass this slice exists to close -----------------------------------


@pytest.mark.django_db
def test_rotating_xff_no_longer_buys_fresh_buckets(client, login_url):
    """The original finding: rotating a junk XFF prefix allowed every guess.

    DRF's get_ident joined the whole XFF chain into the throttle key, so each new
    prefix was a new bucket. Our get_ident ignores XFF entirely.
    """
    codes = []
    for i in range(40):
        response = client.post(
            login_url,
            {"email": "victim@example.com", "password": f"guess-{i}"},
            content_type="application/json",
            HTTP_X_FORWARDED_FOR=f"10.0.{i}.{i}, 172.16.0.1",
        )
        codes.append(response.status_code)

    assert 429 in codes, "rotating X-Forwarded-For still mints fresh throttle buckets"
    # login_burst is 5/min, so the throttle should bite very early, not at attempt 61.
    assert codes.index(429) <= 6, f"first 429 at attempt {codes.index(429) + 1}, expected <= 6"


@pytest.mark.django_db
def test_password_spraying_across_many_emails_is_capped(client, login_url):
    """The hole that listing throttle_classes on LoginView originally opened.

    DRF REPLACES the global defaults when a view sets throttle_classes, so the two
    email-keyed windows left /auth/token/ with no volume cap: one guess each against
    thousands of addresses touches no per-email counter. Verified unmetered against
    production before LoginIPThrottle existed -- 14 emails, 14 x 401, never a 429.
    """
    codes = []
    for i in range(36):
        response = client.post(
            login_url,
            {"email": f"spray-{i}@example.com", "password": "Password123!"},
            content_type="application/json",
        )
        codes.append(response.status_code)

    assert 429 in codes, "password spraying across rotating emails was not capped"


@pytest.mark.django_db
def test_login_ip_throttle_is_listed_first(client, login_url):
    """Order matters: the IP throttle must record before the email throttle reads
    request.data, which can raise ParseError on a malformed body."""
    from apps.accounts.throttling import LoginIPThrottle
    from apps.accounts.views import LoginView

    assert LoginView.throttle_classes[0] is LoginIPThrottle


@pytest.mark.django_db
def test_login_throttle_is_keyed_per_email_not_globally(client, login_url):
    """One account being hammered must not lock every other customer out."""
    for i in range(8):
        client.post(
            login_url,
            {"email": "victim@example.com", "password": f"guess-{i}"},
            content_type="application/json",
        )

    other = client.post(
        login_url,
        {"email": "someone-else@example.com", "password": "whatever"},
        content_type="application/json",
    )
    assert other.status_code != 429


@pytest.mark.django_db
def test_omitting_the_email_field_does_not_disable_the_throttle(client, login_url):
    """A None cache key means 'no throttle' in DRF -- the obvious bypass to try."""
    codes = [
        client.post(login_url, {"password": "x"}, content_type="application/json").status_code
        for _ in range(10)
    ]
    assert 429 in codes, "requests with no email field were never throttled"


# --- registration: the spam cannon -------------------------------------------


@pytest.fixture
def tight_register_ip_rate(monkeypatch):
    """Pin register_ip low so the test asserts the CAP EXISTS without depending on the
    configured number, which is deliberately loose (all storefront traffic shares one
    Vercel egress IP, so a tight value would cap the whole shop).

    Patching the class attribute, NOT django settings: DRF binds
    `SimpleRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES` at import
    time, so a settings override never reaches an already-imported throttle class.
    """
    from apps.accounts.throttling import RegisterIPThrottle

    monkeypatch.setattr(
        RegisterIPThrottle,
        "THROTTLE_RATES",
        {**RegisterIPThrottle.THROTTLE_RATES, "register_ip": "5/hour"},
    )
    yield


@pytest.mark.django_db
def test_register_is_volume_capped_per_ip_even_with_rotating_emails(
    client, register_url, tight_register_ip_rate
):
    """The email key cannot cap volume; the IP key must.

    RegisterView mails the SUBMITTED address, so unlimited registrations with rotating
    recipients is a spam cannon aimed at strangers from our own sending domain.
    """
    codes = []
    for i in range(10):
        response = client.post(
            register_url,
            {
                "email": f"stranger-{i}@example.com",
                "password": "sufficiently-long-password-123",
                "first_name": "A",
            },
            content_type="application/json",
            HTTP_X_FORWARDED_FOR=f"10.9.{i}.{i}",
        )
        codes.append(response.status_code)

    assert 429 in codes, "register accepted unlimited rotating-recipient signups from one IP"
    assert codes.index(429) <= 6, "register_ip pinned to 5/hour; expected the cap to bite by 6"


@pytest.mark.django_db
def test_register_throttle_prefers_cf_connecting_ip_over_xff(client, register_url):
    """Two different CF-Connecting-IPs are two buckets, even with identical XFF."""
    for i in range(11):
        client.post(
            register_url,
            {"email": f"a-{i}@example.com", "password": "sufficiently-long-pw-123", "first_name": "A"},
            content_type="application/json",
            HTTP_CF_CONNECTING_IP="203.0.113.10",
            HTTP_X_FORWARDED_FOR="10.0.0.1",
        )

    fresh = client.post(
        register_url,
        {"email": "b@example.com", "password": "sufficiently-long-pw-123", "first_name": "B"},
        content_type="application/json",
        HTTP_CF_CONNECTING_IP="203.0.113.99",
        HTTP_X_FORWARDED_FOR="10.0.0.1",
    )
    assert fresh.status_code != 429


# --- password reset ----------------------------------------------------------


@pytest.mark.django_db
def test_password_reset_is_throttled_per_target_email(client, reset_url):
    """Protects the victim's inbox, which is the only thing an IP key cannot do."""
    codes = [
        client.post(
            reset_url,
            {"email": "victim@example.com"},
            content_type="application/json",
            HTTP_CF_CONNECTING_IP=f"198.51.100.{i}",  # different IP every time
        ).status_code
        for i in range(8)
    ]
    assert 429 in codes, "reset emails to one address were not capped across IPs"


# --- unit-level -------------------------------------------------------------


def test_client_ip_ignores_x_forwarded_for(rf):
    request = rf.post("/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="10.0.0.9")
    assert client_ip(request) == "10.0.0.9"


def test_client_ip_prefers_cloudflare_header(rf):
    request = rf.post(
        "/", HTTP_CF_CONNECTING_IP="203.0.113.7", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="10.0.0.9"
    )
    assert client_ip(request) == "203.0.113.7"


def test_email_key_is_hashed_not_raw(rf):
    """Customer addresses must not sit in cache keys."""

    class _T(_EmailKeyedThrottle):
        scope = "login_burst"

    request = rf.post("/")
    request.data = {"email": "Someone@Example.COM "}
    key = _T().get_cache_key(request, view=None)
    assert "someone@example.com" not in key
    assert "Someone@Example.COM" not in key


def test_email_key_is_case_and_whitespace_insensitive(rf):
    """Otherwise ' Victim@x.com' and 'victim@x.com' are two buckets for one account."""

    class _T(_EmailKeyedThrottle):
        scope = "login_burst"

    a, b = rf.post("/"), rf.post("/")
    a.data = {"email": "Victim@Example.com"}
    b.data = {"email": "  victim@example.com  "}
    assert _T().get_cache_key(a, view=None) == _T().get_cache_key(b, view=None)
