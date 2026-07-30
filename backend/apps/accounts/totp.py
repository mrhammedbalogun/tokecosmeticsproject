"""The staff second factor: secrets, verification, brute-force caps, recovery codes.

This module holds the DECISIONS. `views.py` holds the HTTP shape and `models.py` the
storage. The split is the same one `invites.py` uses and for the same reason: the
concurrency test drives `consume_recovery_code` from two real threads, which is only
possible because the single-use claim is a function rather than something buried in a
request/response cycle.

── WHY pyotp AND NOT django-otp ──────────────────────────────────────────────────────

django-otp's value is its session middleware and its `django.contrib.admin`
integration — exactly the machinery this project does not have and does not want.
Staff auth here is pure JWT with a private audience claim
(`apps/accounts/authentication.py`); adopting django-otp would mean fighting its
request/session model in order to discard most of it. pyotp is a thin RFC 6238
implementation, and the ceremony is already ours.

── WHY THE SECRET IS ENCRYPTED AND NOT HASHED ────────────────────────────────────────

An invite token is hashed because verifying it only requires comparing digests. A TOTP
secret cannot be: verifying a code means REGENERATING it, so the secret has to come
back out in plaintext. Encryption at rest is therefore the only available control, and
what it buys is specific and worth stating: the database does not stay on this box. It
leaves nightly for an S3 bucket whose write credential can also delete, with versioning
off (memory `project_tokecosmetics_s3_backup_risk`). In a stolen dump, password hashes
are PBKDF2 and slow to attack; plaintext TOTP secrets would be the weakest artifact in
the file — the second factor for every staff account, free, and undetectably. Encrypting
under an env-held key makes that dump non-fatal, because a backup never contains the env.

Fernet (AES-128-CBC + HMAC-SHA256, from `cryptography`) is the boring, most-vetted
choice available. There is deliberately no homegrown crypto anywhere in this feature.

── THE TWO BRUTE-FORCE LAYERS, AND WHY ONE IS NOT ENOUGH ─────────────────────────────

A six-digit code with +/-1 step of drift means roughly three valid values at any
instant: p ~ 3e-6 per guess.

**Layer 1 — per preauth token, 5 failures.** The token dies; it is a JWT, so
invalidation is a denylist entry keyed on its `jti` with a TTL equal to the token's
remaining life, checked in `AdminPreauthJWTAuthentication` so all three endpoints get
it without remembering to.

Layer 1 alone is beatable, and the asymmetry that makes it beatable is worth
understanding rather than assuming: an attacker who already holds the staff password
performs *successful* password authentications, so `admin_login_ip` and
`admin_login_email` — which count FAILURES (see `throttling.py`) — never increment. The
only per-ceremony cost is one solved Turnstile token, about $0.001. At 5 guesses per
ceremony, even odds needs ~46,000 ceremonies: roughly $46. That is not a fence.

**Layer 2 — per user, 20 failures per rolling hour, then a one-hour hard deny.** This is
the cap that bites: ~480 days for a coin flip, and the first hour raises a Sentry event.
It is keyed on the USER — a value read from a validated token, not from anything a
caller supplies — so it is not the denial button that a request-counting, address-keyed
throttle would be. THE LOCKOUT OBJECTION THAT RESHAPED THE LOGIN THROTTLES DOES NOT
APPLY HERE, and the alert text says so out loud: reaching this cap requires the staff
password, so the operator's first action is to rotate the password, not to clear the
bucket.

Both counters live in the cache — Redis in production, LocMem in dev and tests. Losing
them (a Redis restart, a `FLUSHALL`) re-opens the window rather than locking anyone out,
which is the right direction for a control whose alternative failure mode is denying the
only administrator access to his own store.

KNOWN RACE, recorded rather than papered over: the sliding-window read-modify-write is
not atomic, so perfectly concurrent requests can each read the same history and cost the
attacker fewer than one increment apiece. At p ~ 3e-6 per guess the difference is
irrelevant, and the alternative (a Lua script or a distributed lock on the auth path)
buys nothing for real cost.

── DRIFT ────────────────────────────────────────────────────────────────────────────

+/-1 step, i.e. 90 seconds of acceptance. NOT +/-2: it doubles both the guess surface
and the replay window and buys nothing on a population whose server clock we control.
That control is an assumption with an operational cost — `docs/runbooks/admin-gate.md`
§6 carries a deploy check that `timedatectl` reports NTP sync, because a drifting VPS
clock breaks TOTP silently for everyone at once.

── REPLAY ───────────────────────────────────────────────────────────────────────────

`StaffTOTP.last_verified_step` records the highest step ever accepted, and any step at
or below it is refused. The update is one atomic conditional UPDATE inside the same
transaction as the success path, so two requests carrying the same code cannot both
win — the same discipline (and the same two-thread test) as the invite claim.

── RECOVERY CODES ───────────────────────────────────────────────────────────────────

Eight codes of `secrets.token_hex(10)`: 80 bits, twenty typable hex characters. At 80
bits online guessing is not a threat, so the invite-token reasoning transfers exactly —
SHA-256, lookup by digest, no slow KDF (a work factor buys nothing against that entropy
and hands an endpoint a CPU-DoS lever). Single-use via the same atomic conditional
UPDATE.

Their scope is the TOTP FACTOR ONLY, never the ceremony: they are accepted solely from
a caller who already holds a preauth token, which means password and Turnstile came
first. There is no bare recovery-code-to-session path, so a leaked code sheet is worth
nothing on its own.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time

import pyotp
from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.core.log_safety import scrub

security_logger = logging.getLogger("apps.security")

# --- parameters ---------------------------------------------------------------

# 32 base32 characters = 160 bits, RFC 4226 §4 R6's recommendation and what every
# authenticator app is built around.
SECRET_LENGTH = 32
TOTP_INTERVAL = 30  # seconds per step (RFC 6238 default; changing it breaks every app)
TOTP_DIGITS = 6
# Steps of clock skew accepted either side of now. See the module docstring for why
# this is 1 and not 2.
TOTP_DRIFT_STEPS = 1

# Shown in the authenticator app as "<ISSUER> (<email>)".
ISSUER = "Toke Cosmetics Admin"

PREAUTH_FAILURE_LIMIT = 5

USER_FAILURE_LIMIT = 20
USER_FAILURE_WINDOW = 3600  # seconds — a rolling hour
USER_LOCK_SECONDS = 3600  # how long the hard deny lasts once the cap is reached

RECOVERY_CODE_COUNT = 8
RECOVERY_CODE_BYTES = 10  # -> 80 bits, 20 hex characters


def _now() -> float:
    """Wall clock, in one place so tests can pin it."""
    return time.time()


# --- secret material ----------------------------------------------------------


def new_secret() -> str:
    return pyotp.random_base32(length=SECRET_LENGTH)


def _fernet() -> MultiFernet:
    """Primary key first, decrypt-only fallbacks after.

    `MultiFernet` encrypts with the FIRST key and decrypts with any of them, which is
    what makes rotation a background job instead of a flag day. Built per call rather
    than at import so `settings` overrides in tests (and a future runtime reload) are
    honoured; constructing a Fernet is parsing a 32-byte key, not a KDF.
    """
    keys = [settings.TOTP_ENCRYPTION_KEY, *settings.TOTP_ENCRYPTION_KEY_FALLBACKS]
    return MultiFernet([Fernet(_as_bytes(key)) for key in keys if key])


def _as_bytes(key) -> bytes:
    return key.encode("utf-8") if isinstance(key, str) else key


def encrypt_secret(raw: str) -> str:
    """Ciphertext for the database column. Text rather than bytes so the column reads
    the same on every backend and in every dump."""
    return _fernet().encrypt(raw.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Raises `cryptography.fernet.InvalidToken` if no configured key can read it.

    Deliberately NOT caught here. A secret that cannot be decrypted means the key was
    rotated without running `rotate_totp_key`, or the wrong key is deployed — a
    configuration emergency that must surface as a 500 and a Sentry event, not as "your
    code is wrong", which would send the operator hunting for the wrong problem.
    """
    return _fernet().decrypt(_as_bytes(ciphertext)).decode("utf-8")


def provisioning_uri(user, secret: str) -> str:
    """The `otpauth://` URI the QR code encodes.

    RETURNED ONCE AND NEVER STORED OR LOGGED: it contains the secret in the query
    string, so a copy of it in a log line is a copy of the second factor.
    """
    return pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL).provisioning_uri(
        name=user.email, issuer_name=ISSUER
    )


# --- verification -------------------------------------------------------------


def verify_code(secret: str, code, *, now: float | None = None) -> int | None:
    """The step number a code matches, or None.

    Returns the STEP rather than a boolean because the caller needs it for the replay
    guard — `pyotp.TOTP.verify` answers only yes/no, which is not enough to refuse a
    code that was already used.

    `hmac.compare_digest` rather than `==`: a plain comparison on a secret-derived value
    is a timing oracle. It is a weak one for a six-digit code, and free to avoid.
    """
    if not isinstance(code, str):
        return None
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != TOTP_DIGITS:
        return None

    now = _now() if now is None else now
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL)
    current = int(now) // TOTP_INTERVAL
    for step in range(current - TOTP_DRIFT_STEPS, current + TOTP_DRIFT_STEPS + 1):
        if hmac.compare_digest(totp.at(step * TOTP_INTERVAL), code):
            return step
    return None


# --- layer 1: per preauth token -----------------------------------------------


def _preauth_fail_key(jti: str) -> str:
    return f"totp:preauth_fail:{jti}"


def _preauth_denied_key(jti: str) -> str:
    return f"totp:preauth_denied:{jti}"


def preauth_is_denied(jti: str) -> bool:
    """Read by `AdminPreauthJWTAuthentication` on every preauth-authenticated request."""
    return bool(jti) and cache.get(_preauth_denied_key(jti)) is not None


def record_preauth_failure(jti: str, *, ttl: int) -> int:
    """Count one failure against this token; deny it at the limit. Returns the count.

    `ttl` is the token's REMAINING life. Both keys expire with the token, because after
    that the JWT's own `exp` refuses it and a denylist entry for a dead token is just
    memory nobody will ever read.
    """
    if not jti:
        return 0
    ttl = max(int(ttl), 1)
    key = _preauth_fail_key(jti)
    count = (cache.get(key) or 0) + 1
    cache.set(key, count, ttl)
    if count >= PREAUTH_FAILURE_LIMIT:
        cache.set(_preauth_denied_key(jti), True, ttl)
    return count


def reset_preauth_failures(jti: str) -> None:
    if jti:
        cache.delete(_preauth_fail_key(jti))


# --- layer 2: per user, across preauth tokens ---------------------------------


def _user_fail_key(user) -> str:
    return f"totp:user_fail:{user.pk}"


def _user_lock_key(user) -> str:
    return f"totp:user_lock:{user.pk}"


def user_failure_count(user) -> int:
    """Failures inside the rolling window. Exposed for tests and for the reset check."""
    now = _now()
    history = cache.get(_user_fail_key(user)) or []
    return len([t for t in history if t > now - USER_FAILURE_WINDOW])


def user_is_locked(user) -> bool:
    return cache.get(_user_lock_key(user)) is not None


def record_user_failure(user) -> int:
    """Count one failure against the account and, at the cap, hard-deny it for an hour.

    The window is a list of timestamps rather than a counter so that failures age out
    individually — a staff member who fumbles five codes a day for four days is not
    treated as an attack.
    """
    now = _now()
    key = _user_fail_key(user)
    history = [t for t in (cache.get(key) or []) if t > now - USER_FAILURE_WINDOW]
    history.append(now)
    cache.set(key, history, USER_FAILURE_WINDOW)

    if len(history) >= USER_FAILURE_LIMIT and not user_is_locked(user):
        cache.set(_user_lock_key(user), True, USER_LOCK_SECONDS)
        # ERROR -> a Sentry event. This is the one alert in the whole feature that
        # someone should act on immediately, and the message says what the action is:
        # burning this bucket requires the account's PASSWORD, so by the time it fires
        # the password is the thing that has already been lost.
        security_logger.error(
            "TOTP brute force in progress against %s: %d failed codes in an hour, "
            "verification hard-denied for %d minutes — assume the password is "
            "compromised, rotate it",
            scrub(getattr(user, "email", "<unknown>")),
            len(history),
            USER_LOCK_SECONDS // 60,
        )
    return len(history)


def reset_user_failures(user) -> None:
    cache.delete(_user_fail_key(user))
    cache.delete(_user_lock_key(user))


# --- recovery codes -----------------------------------------------------------


def hash_recovery_code(raw: str) -> str:
    """SHA-256, no work factor — 80 bits leaves nothing to enumerate, and a slow KDF on
    a code submitted by an unauthenticated-ish caller is a CPU-DoS lever. Same reasoning
    as `invites.hash_token`."""
    return hashlib.sha256(raw.strip().lower().encode("utf-8")).hexdigest()


def issue_recovery_codes(user) -> list[str]:
    """Replace this user's whole code set and return the RAW codes.

    They exist in this process exactly once: the response body carries them, nothing
    stores or logs them. Replacing rather than topping up is deliberate — a set is
    printed or saved as a unit, so a mixture of old and new is a sheet that is partly
    wrong, which is worse than one that is entirely stale.
    """
    from apps.accounts.models import StaffRecoveryCode

    StaffRecoveryCode.objects.filter(user=user).delete()
    raw_codes = [secrets.token_hex(RECOVERY_CODE_BYTES) for _ in range(RECOVERY_CODE_COUNT)]
    StaffRecoveryCode.objects.bulk_create(
        [StaffRecoveryCode(user=user, code_hash=hash_recovery_code(code)) for code in raw_codes]
    )
    return raw_codes


def consume_recovery_code(user, raw) -> bool:
    """Burn one code. True if this caller is the one that burned it.

    ONE ATOMIC CONDITIONAL UPDATE, exactly as `invites.claim` does it: the predicate is
    in the WHERE clause, so the database evaluates it under the row lock and of two
    concurrent callers exactly one sees a rowcount of 1. Written the obvious way — read
    the row, check `used_at`, save — both callers see an unused code and both win.

    Scoped to `user` as well as to the digest so one staff member's sheet can never be
    used against another's account, even in the (impossible, uniquely-indexed) event of
    a digest collision.
    """
    from apps.accounts.models import StaffRecoveryCode

    if not isinstance(raw, str) or not raw.strip():
        return False
    burned = StaffRecoveryCode.objects.filter(
        user=user, code_hash=hash_recovery_code(raw), used_at__isnull=True
    ).update(used_at=timezone.now())
    return burned == 1
