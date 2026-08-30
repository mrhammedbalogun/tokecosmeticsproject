"""Normalise, then SHA-256. The one place personal data is prepared for an ad platform.

Every platform in Plan-44 wants the same thing in the same format — lowercase, trimmed,
punctuation removed, then hex SHA-256 — and every one of them fails the SAME way when it
is done wrong: **silently**. A badly normalised email is not rejected, it simply never
matches anybody, and the only symptom is a match-quality score nobody is watching.

So the normalisation lives here, once, with the vendor rules written down beside it:

  email    trim, lowercase. Nothing else — no dot-stripping, no plus-stripping. Meta,
           TikTok and Snap all hash the address AS THE CUSTOMER TYPED IT (modulo case),
           and "helpfully" canonicalising gmail dots produces a hash that matches
           nothing on any of them.
  phone    digits only, country code included, no `+`, no spaces, no punctuation. Our
           column is already E.164 (`+2348012345678`), so this is a strip, not a guess.
           A number WITHOUT a country code must not be sent: "08012345678" hashes to a
           value that matches a different person in a different country, or nobody.
  names    trim, lowercase, strip everything that is not a letter. Meta's own examples
           fold accents; we do not, deliberately — see `_letters_only`.
  city     trim, lowercase, remove spaces and punctuation ("Lekki Phase 1" -> "lekkiphase1").
  state    lowercase two-letter code where one exists, else the lowercased name.
  zip      trim, lowercase, first five characters for US; ours are rarely present at all.
  country  lowercase ISO-3166 alpha-2.

WHAT MUST NEVER COME THROUGH HERE: `fbc`, `fbp`, `ttclid`, `ttp`, `sc_click_id`,
`sc_cookie1`, `client_ip_address`, `client_user_agent`. All four vendors require those
RAW. Hashing them is not an error anybody reports; it just destroys the match.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

_NON_DIGITS = re.compile(r"\D")
_NON_LETTERS = re.compile(r"[^a-z]")
_NON_ALNUM = re.compile(r"[^a-z0-9]")


def sha256_hex(value: str) -> str:
    """Hex SHA-256 of an ALREADY-NORMALISED string. Empty in, empty out — an empty
    string has a perfectly good hash, and sending it would assert we know an identifier
    we do not, which is worse for match quality than sending nothing."""
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fold_accents(value: str) -> str:
    """NFKD, then drop the combining marks: "Adéwálé" -> "Adewale".

    Applied to NAMES ONLY. The vendors' documented examples fold accents in names, and
    a Nigerian customer list carries plenty of them. It is NOT applied to emails, where
    the address is an exact string and folding it would produce a hash of an address
    that does not exist.
    """
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def normalize_phone(value: str | None) -> str:
    """Digits only. Returns "" for anything that did not arrive in E.164.

    The `+` prefix is the ONLY evidence we have that a country code is present, and a
    number without one is worse than no number at all — it matches the wrong person.
    `apps.core.phones.normalize_e164` is what puts the `+` there in the first place, so
    in practice everything stored since Plan-24 passes; legacy rows that predate it are
    dropped here rather than guessed at.
    """
    raw = (value or "").strip()
    if not raw.startswith("+"):
        return ""
    digits = _NON_DIGITS.sub("", raw)
    # A country code plus a subscriber number is never shorter than 8 digits and never
    # longer than 15 (ITU-T E.164). Outside that it is not a phone number.
    return digits if 8 <= len(digits) <= 15 else ""


def normalize_name(value: str | None) -> str:
    return _NON_LETTERS.sub("", _fold_accents((value or "").strip().lower()))


def normalize_city(value: str | None) -> str:
    return _NON_ALNUM.sub("", _fold_accents((value or "").strip().lower()))


def normalize_state(value: str | None) -> str:
    """Lowercased, punctuation removed. Meta prefers a two-letter code for US states and
    accepts the name elsewhere; Nigerian states have no such code, so the name is what
    there is. Not truncated to two characters — "la" is not Lagos to anybody."""
    return _NON_ALNUM.sub("", _fold_accents((value or "").strip().lower()))


def normalize_zip(value: str | None) -> str:
    """Lowercase, spaces removed. UK postcodes keep their full form; a US ZIP+4 is cut
    to the leading five, which is what Meta documents."""
    cleaned = _NON_ALNUM.sub("", (value or "").strip().lower())
    return cleaned[:5] if cleaned.isdigit() and len(cleaned) > 5 else cleaned


def normalize_country(value: str | None) -> str:
    code = _NON_LETTERS.sub("", (value or "").strip().lower())
    return code if len(code) == 2 else ""


def hashed_email(value: str | None) -> str:
    return sha256_hex(normalize_email(value))


def hashed_phone(value: str | None) -> str:
    return sha256_hex(normalize_phone(value))


def hashed_name(value: str | None) -> str:
    return sha256_hex(normalize_name(value))


def hashed_city(value: str | None) -> str:
    return sha256_hex(normalize_city(value))


def hashed_state(value: str | None) -> str:
    return sha256_hex(normalize_state(value))


def hashed_zip(value: str | None) -> str:
    return sha256_hex(normalize_zip(value))


def hashed_country(value: str | None) -> str:
    return sha256_hex(normalize_country(value))
