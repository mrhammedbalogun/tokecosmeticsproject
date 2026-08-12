"""Email one-time codes — the second factor for staff who chose inbox over app.

This module holds the DECISIONS, exactly as `totp.py` does for the authenticator
method; `views.py` holds the HTTP shape. There is no model: a code lives for five
minutes, so its natural home is the cache (Redis in prod, LocMem in dev/tests) —
losing the cache invalidates outstanding codes, which fails in the safe direction.

── WHAT AN EMAIL CODE IS WORTH, honestly ─────────────────────────────────────────────

It downgrades the second factor to "whoever controls the staff member's inbox", which
is strictly weaker than a TOTP secret that never leaves a phone. That trade is offered
deliberately (some staff cannot or will not run an authenticator app) but it is never
allowed to weaken anyone else's account: a confirmed TOTP enrolment REFUSES the email
path outright (`views.AdminEmailOTPRequestView`), so an attacker holding a password
cannot route around an authenticator by asking for mail.

── WHY THE CODE IS HASHED IN THE CACHE ───────────────────────────────────────────────

A six-digit code is 20 bits — trivially enumerable offline, so a bare SHA-256 would
only be obfuscation. `salted_hmac` keys the digest with `SECRET_KEY`, which a cache
dump does not contain; same reasoning as the Fernet key for TOTP secrets. Online
guessing is what actually matters, and it is capped three ways: 5 attempts per code
(below), then the two layers every second-factor failure already feeds — 5 per preauth
token and 20 per user-hour (`totp.py`) — because the confirm view counts an email miss
and a TOTP miss identically.

── THE SEND SIDE NEEDS ITS OWN CAPS ──────────────────────────────────────────────────

Verification caps do not stop someone with a staff password turning the endpoint into
a mail cannon at the staff member's own inbox (annoyance, Resend quota, and a fog of
real-looking security mail to hide one real attempt in). Two caps, both per USER — the
value read from a validated preauth token, so neither is a lockout button an outsider
can press:

* a 60-second cooldown between sends, answered politely (the view returns 200 with
  `retry_after` rather than an error, so a refreshed page does not scold anyone);
* 6 sends per rolling hour, after which the send endpoint 429s. The cap raises no
  Sentry event of its own: reaching it requires the password, and the wrong-code and
  user-lock alerts already page on the attack that matters.

── LIFETIME ──────────────────────────────────────────────────────────────────────────

Five minutes: an email round trip with slack, comfortably inside the ten-minute
preauth window so a code can never outlive the ceremony that requested it. Requesting
a new code REPLACES the old one — exactly one code is live per user at any moment,
so the guess surface never grows with impatience.
"""
from __future__ import annotations

import hmac
import logging
import secrets

from django.core.cache import cache
from django.utils.crypto import salted_hmac

from apps.core.log_safety import scrub

security_logger = logging.getLogger("apps.security")

CODE_DIGITS = 6
CODE_LIFETIME = 300  # seconds — 5 minutes, well inside the 10-minute preauth window
CODE_ATTEMPT_LIMIT = 5  # wrong guesses before the code itself is voided

SEND_COOLDOWN = 60  # seconds between sends
SEND_LIMIT = 6  # per rolling hour
SEND_WINDOW = 3600

# The HMAC key-salt. A constant, not a secret: the secret half is SECRET_KEY.
_HASH_SALT = "apps.accounts.email_otp"


def _code_key(user) -> str:
    return f"email_otp:code:{user.pk}"


def _attempts_key(user) -> str:
    return f"email_otp:attempts:{user.pk}"


def _cooldown_key(user) -> str:
    return f"email_otp:cooldown:{user.pk}"


def _sends_key(user) -> str:
    return f"email_otp:sends:{user.pk}"


def _now() -> float:
    import time

    return time.time()


def _hash_code(code: str) -> str:
    return salted_hmac(_HASH_SALT, code).hexdigest()


def send_wait_seconds(user) -> int:
    """Seconds until this user may be sent another code. 0 means "now".

    Checks the cooldown only — the hourly cap is `send_allowance`, kept separate
    because the two produce different responses (a polite 200 versus a 429).
    """
    issued_at = cache.get(_cooldown_key(user))
    if issued_at is None:
        return 0
    return max(0, int(issued_at + SEND_COOLDOWN - _now()))


def send_allowance(user) -> int:
    """Sends left in the rolling hour. The same timestamp-list shape as
    `totp.record_user_failure`, for the same reason: entries age out individually."""
    now = _now()
    history = [t for t in (cache.get(_sends_key(user)) or []) if t > now - SEND_WINDOW]
    return max(0, SEND_LIMIT - len(history))


def issue_code(user) -> str:
    """Mint a fresh code, replacing any outstanding one, and return it RAW.

    The raw code exists in this process exactly twice: this return value and the email
    body built from it. Never logged — a code in a log line is a second factor in a
    log line, however briefly it lives.

    The caller is responsible for having checked `send_wait_seconds` and
    `send_allowance` first; this function only records the send.
    """
    now = _now()
    code = f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"
    cache.set(_code_key(user), _hash_code(code), CODE_LIFETIME)
    cache.delete(_attempts_key(user))
    cache.set(_cooldown_key(user), now, SEND_COOLDOWN)
    history = [t for t in (cache.get(_sends_key(user)) or []) if t > now - SEND_WINDOW]
    history.append(now)
    cache.set(_sends_key(user), history, SEND_WINDOW)
    return code


def verify_code(user, code) -> bool:
    """Burn the outstanding code if `code` matches it. Single-use by deletion.

    Every wrong guess counts toward `CODE_ATTEMPT_LIMIT`; at the limit the code is
    voided, so five misses force a fresh send even before the per-token and per-user
    layers (which the VIEW charges, alongside this) come into play. The check-and-
    increment here is cache read-modify-write, not atomic — the same recorded,
    accepted race as `totp.record_user_failure`, and worth the same amount: nothing,
    against a 5-attempt cap backed by two more layers.
    """
    if not isinstance(code, str):
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != CODE_DIGITS:
        return False

    stored = cache.get(_code_key(user))
    if stored is None:
        return False

    if hmac.compare_digest(stored, _hash_code(code)):
        # Single-use is decided by the DELETE, not the compare: `cache.delete` returns
        # whether the key still existed, and a Redis DEL is atomic — so of two
        # concurrent submissions of one code, exactly one wins. The same replay
        # discipline as `last_verified_step`, in the storage this factor lives in.
        won = bool(cache.delete(_code_key(user)))
        cache.delete(_attempts_key(user))
        return won

    attempts = (cache.get(_attempts_key(user)) or 0) + 1
    cache.set(_attempts_key(user), attempts, CODE_LIFETIME)
    if attempts >= CODE_ATTEMPT_LIMIT:
        cache.delete(_code_key(user))
        # WARNING, not ERROR: the per-user layer in totp.py raises the Sentry event
        # when a genuine brute force builds; this line explains a voided code to
        # whoever reads the stream.
        security_logger.warning(
            "admin email OTP voided for %s after %d wrong guesses",
            scrub(getattr(user, "email", "<unknown>")),
            attempts,
        )
    return False
