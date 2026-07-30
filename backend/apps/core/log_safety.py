"""Make attacker-supplied text safe to put in a log line.

WHY THIS MODULE EXISTS. `apps.security` is a plain-text stream — the console handler
writes `%(asctime)s %(levelname)s [%(name)s] %(message)s`, one record per line — and
it is the stream that answers "was the admin attacked, and did anyone get in".
Several of its lines interpolate a value the caller chose: the email submitted to a
login endpoint (read from `request.data` before any validation, so it need not be an
email at all) and the path of a throttled request.

A newline in such a value forges a COMPLETE ADDITIONAL LINE, at whatever level and
with whatever wording the attacker likes, into that record. Demonstrated against
`/auth/admin-token/` before this existed: an email of

    attacker@evil.test\\nadmin login succeeded for owner@toke.test

produced a security log containing a clean, entirely fictional success line for the
shop owner — written by an anonymous request that knew no password. That is worse
than no log at all, because a log nobody can trust is read as though it can be.

Length is the same bug at a different scale. Admin login failures log at ERROR, and
ERROR records become Sentry EVENTS carrying the message, so an uncapped field turns
one scripted attacker into both a disk-fill and a quota-burn — and the quota is what
pays for seeing the next attack.

DELETING the offending characters rather than escaping them is deliberate. Escaping
(`\\n` -> backslash-n) preserves more evidence, but it makes the output longer than
the input, which has to be reasoned about alongside the length cap, and the evidence
it preserves is not worth that: nothing downstream parses these lines for structure.
Whatever is left is still one line, still attributable, and still contains enough of
the payload to recognise an attack.

This is NOT an encoder for structured logging. If these lines ever become JSON, the
serialiser handles quoting and this becomes a length cap only.
"""
from __future__ import annotations

# Long enough for the longest legal email address (RFC 5321 caps a path at 254
# octets), short enough that a record stays one readable line.
MAX_LOGGED_LENGTH = 254

_TRUNCATED = "…[truncated]"

# C0 controls, DEL, the C1 block, and the two Unicode separators. The C1 block and
# U+2028/U+2029 are here because `str.splitlines()` — the obvious thing for a script
# reading this stream to call — treats several of them as line breaks even though
# they are not `\n`.
_CONTROL_CHARS = frozenset(
    [*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0), 0x2028, 0x2029]
)
_STRIP_TABLE = dict.fromkeys(_CONTROL_CHARS)


def scrub(value: object, *, limit: int = MAX_LOGGED_LENGTH) -> str:
    """One line's worth of safe text from an arbitrary caller-supplied value.

    Accepts `object` rather than `str` on purpose: the values that reach here come
    out of parsed JSON, so `email` may be a dict, a list, or a number. A logging
    helper that raises on those would turn a 400 into a 500 — the log line is never
    the point of the request, and it must never be the reason one fails.
    """
    text = value if isinstance(value, str) else repr(value)
    text = text.translate(_STRIP_TABLE)
    if len(text) > limit:
        # The marker matters: a silently truncated value reads as a complete one, and
        # someone will later conclude the attacker used a short address.
        text = text[:limit] + _TRUNCATED
    return text
