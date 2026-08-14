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
