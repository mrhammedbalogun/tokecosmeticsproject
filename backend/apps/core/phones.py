"""E.164 phone normalisation — the single place a phone number is judged.

The rule the storefront and API both rely on: a stored contact number is either
empty or strict E.164 ("+2348023900964"). The leading "+" is REQUIRED rather than
guessed — parsing "08023900964" would need a country assumption, and a wrong guess
stores a number that dials someone else. The country choice therefore happens in
the UI (the flag picker), never here.
"""

import re

import phonenumbers

# Formatting noise users paste in with a number: spaces, dots, dashes, brackets.
_NOISE = re.compile(r"[\s\-().]")


def normalize_e164(value: str) -> str:
    """Return the E.164 form of `value`, "" for blank, or raise ValueError.

    The ValueError message is customer-facing (serializers pass it through), so it
    says what to do, not what failed internally.
    """
    raw = _NOISE.sub("", value or "")
    if not raw:
        return ""
    if not raw.startswith("+"):
        raise ValueError("Include the country code, e.g. +2348023900964.")
    try:
        parsed = phonenumbers.parse(raw, None)
    except phonenumbers.NumberParseException:
        raise ValueError("Enter a valid phone number with country code, e.g. +2348023900964.")
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("That phone number does not look valid for its country.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def format_display(value: str, viewer_country: str = "") -> str:
    """A human-readable rendering of a stored E.164 number. Never raises.

    "+2348023900964" -> "0802 390 0964" for a Nigerian reader, "+234 802 390 0964"
    for everyone else. The distinction matters on the store locator: a Lagos
    customer reads and dials the national form, and printing "+234…" to them looks
    like an international call they will be charged for; a customer abroad looking
    up a Lagos stockist needs the country code or the number does not connect.

    FORMATTING ONLY — the stored value is untouched and every `tel:`/`wa.me` link
    is built from the E.164 form, so a prettified string can never be dialled.
    Anything unparseable comes back verbatim rather than raising: this runs on a
    read path serving a public page, and a bad row must degrade to "shows the raw
    number", never to a 500.
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = phonenumbers.parse(raw, None)
    except phonenumbers.NumberParseException:
        return raw
    national = phonenumbers.region_code_for_number(parsed)
    fmt = (
        phonenumbers.PhoneNumberFormat.NATIONAL
        if national and national.upper() == (viewer_country or "").upper()
        else phonenumbers.PhoneNumberFormat.INTERNATIONAL
    )
    return phonenumbers.format_number(parsed, fmt)
