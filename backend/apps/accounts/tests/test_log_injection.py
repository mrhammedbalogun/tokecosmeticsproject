"""Attacker-controlled text must not be able to write the security log itself.

WHY THIS FILE EXISTS. `apps.security` is a plain-text stream: the console handler
writes `%(asctime)s %(levelname)s [%(name)s] %(message)s` and one record becomes one
line. Every line in it is evidence — it is the stream that answers "was the admin
attacked, and did anyone get in". Three of its lines interpolate a value the caller
chose, and none of them sanitised it:

* `admin login failed for %s` / `admin login succeeded for %s` — the submitted email,
  read from `request.data` BEFORE any validation, so it need not be an email at all.
* `login failed for %s` — the same value arriving via the `user_login_failed` signal
  on the customer door.
* `throttled: %s` — `request.get_full_path()`. This one is hardening rather than a
  demonstrated hole today (see the test at the bottom for exactly why), and it is
  labelled as such rather than folded in with the other two.

A newline in any of them forges a whole extra line, at a level and with a wording of
the attacker's choosing, into the one record anyone will later trust. Demonstrated
against `/auth/admin-token/`: posting an email of
`x@evil.test\\nadmin login succeeded for owner@toke.test` produced a security log
containing a clean, entirely fictional success line for the shop owner.

Length is the same bug at a different scale: there was no cap, so a 50 KB `email`
field wrote 50 KB per attempt into stdout, into the container log, and — because
admin failures log at ERROR — into Sentry, whose free tier is exactly what the
observability work exists to protect.

The fix is one helper (`apps.core.log_safety.scrub`) applied at every one of those
sites, and these tests are per-site rather than helper-only on purpose: the helper
being correct is worth nothing if a call site forgets it.
"""
import logging

import pytest
from rest_framework.test import APIClient

from apps.core.log_safety import MAX_LOGGED_LENGTH, scrub

pytestmark = pytest.mark.django_db

PW = "Str0ng!pass9"
ADMIN_TOKEN = "/api/v1/auth/admin-token/"
CUSTOMER_TOKEN = "/api/v1/auth/token/"

# The payload: an address, a newline, and a complete forged log line. Nothing exotic —
# a JSON string literal carries `\n` natively, so this costs an attacker nothing.
FORGED_LINE = "admin login succeeded for owner@toke.test"
INJECTION = f"attacker@evil.test\n{FORGED_LINE}"

# Characters that end a line for something that reads this stream. \n and \r are the
# obvious ones; NEL, LINE SEPARATOR and PARAGRAPH SEPARATOR are treated as line breaks
# by Python's own `str.splitlines`, which is what a log-processing script most likely
# uses.
LINE_BREAKS = ("\n", "\r", "\x0b", "\x0c", "\x85", "\u2028", "\u2029")


def _security_records(caplog):
    return [rec for rec in caplog.records if rec.name == "apps.security"]


def _assert_single_line(records):
    for rec in records:
        message = rec.getMessage()
        assert len(message.splitlines()) <= 1, (
            f"one log record produced several lines: {message!r}"
        )
        for char in LINE_BREAKS:
            assert char not in message, f"{char!r} survived into a security log line"


# --- the helper ---------------------------------------------------------------


def test_scrub_removes_every_line_break():
    for char in LINE_BREAKS:
        assert char not in scrub(f"a{char}b")


def test_scrub_removes_other_control_characters():
    """Not only line breaks. A terminal reading this stream interprets escape
    sequences, so `\\x1b[2J` clears the reader's screen and `\\x08` rubs out what was
    written before it — both let a log line lie about its own contents without ever
    containing a newline."""
    assert "\x1b" not in scrub("a\x1b[2Jb")
    assert "\x08" not in scrub("a\x08b")
    assert "\x00" not in scrub("a\x00b")


def test_scrub_caps_the_length_and_says_that_it_did():
    scrubbed = scrub("x" * 50_000)
    assert len(scrubbed) < 500
    assert "truncated" in scrubbed, "a truncated value must not read as a complete one"


def test_scrub_leaves_an_ordinary_address_alone():
    """The cure must not be worse than the disease: these lines exist to say WHICH
    account is being attacked, so the common case has to survive intact."""
    assert scrub("shopper+tag@toke.test") == "shopper+tag@toke.test"


def test_scrub_survives_a_non_string():
    """`request.data["email"]` is whatever JSON contained — a dict, a list, a number.
    A logging helper that raises turns a 400 into a 500."""
    assert scrub({"not": "a string"})
    assert scrub(None)


# --- the call sites -----------------------------------------------------------


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(
        email="owner@toke.test", password=PW, is_staff=True
    )


def test_admin_login_cannot_forge_a_line_in_the_security_log(caplog):
    """THE DEMONSTRATION. Before the fix this test found a complete, well-formed
    `admin login succeeded for owner@toke.test` line in the security log, written by
    an anonymous request that neither knew the owner's password nor solved a
    Turnstile challenge."""
    with caplog.at_level(logging.INFO, logger="apps.security"):
        r = APIClient().post(
            ADMIN_TOKEN, {"email": INJECTION, "password": "nope"}, format="json"
        )
    assert r.status_code == 401
    records = _security_records(caplog)
    assert records
    _assert_single_line(records)
    for rec in records:
        assert not rec.getMessage().startswith(FORGED_LINE)


def test_admin_login_caps_the_size_of_a_logged_address(caplog):
    """Every admin failure logs at ERROR, which Sentry turns into an EVENT carrying
    the message. Uncapped, one scripted attacker fills the log volume and the Sentry
    quota at the same time, and the quota is what pays for seeing the next attack."""
    with caplog.at_level(logging.INFO, logger="apps.security"):
        APIClient().post(
            ADMIN_TOKEN, {"email": "x" * 50_000, "password": "nope"}, format="json"
        )
    for rec in _security_records(caplog):
        assert len(rec.getMessage()) < MAX_LOGGED_LENGTH + 200


def test_a_successful_admin_login_logs_a_scrubbed_address(owner, caplog):
    """The success line takes the SUBMITTED string, not the stored one. It has to have
    matched a real account to get here, so this is belt-and-braces — but the belt is
    free and the line is the most trusted one in the file."""
    with caplog.at_level(logging.INFO, logger="apps.security"):
        r = APIClient().post(
            ADMIN_TOKEN, {"email": owner.email, "password": PW}, format="json"
        )
    assert r.status_code == 200
    _assert_single_line(_security_records(caplog))


def test_customer_login_failure_cannot_forge_a_line(caplog):
    """The `user_login_failed` receiver in signals.py takes its email straight from
    the credentials dict Django passes it. `_clean_credentials` masks the PASSWORD and
    nothing else, so the address arrives exactly as submitted."""
    with caplog.at_level(logging.INFO, logger="apps.security"):
        APIClient().post(
            CUSTOMER_TOKEN, {"email": INJECTION, "password": "nope"}, format="json"
        )
    records = _security_records(caplog)
    assert records, "a failed customer login must still be logged"
    _assert_single_line(records)


def test_the_throttle_line_scrubs_the_path_it_reports(caplog):
    """The throttle line is the ONLY signal several endpoints emit — password reset
    deliberately always answers 200 — so it is the last one that should be forgeable.

    HONEST SCOPE, because this one is hardening rather than a demonstrated hole and
    saying otherwise would be exactly the kind of overclaiming this branch is fixing:
    `get_full_path()` percent-encodes the query string through `iri_to_uri`, and a
    path containing a raw newline has to survive URL resolution first. So the handler
    is driven directly here. It is worth doing anyway — Django's `str` path converter
    is `[^/]+`, which DOES match a newline, so a future throttled route with a `<str:>`
    segment would make this live without anyone touching this file.
    """
    from rest_framework.exceptions import Throttled

    from config.exception_handler import logging_exception_handler

    class _ForgedPath:
        def get_full_path(self):
            return "/api/v1/anything/\nthrottled: nothing to see here"

    with caplog.at_level(logging.INFO, logger="apps.security"):
        logging_exception_handler(Throttled(wait=60), {"request": _ForgedPath()})

    throttle_records = [
        rec for rec in _security_records(caplog) if "throttled" in rec.getMessage()
    ]
    assert throttle_records
    _assert_single_line(throttle_records)
