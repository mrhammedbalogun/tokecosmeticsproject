"""The normalisation rules, pinned.

Every one of these is a rule that fails SILENTLY in production: a wrongly normalised
identifier is accepted by all four platforms and matches nobody, so nothing anywhere
reports an error. The suite is the only place the rules are enforced at all.
"""
from __future__ import annotations

import hashlib

from apps.marketing import hashing


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_email_is_trimmed_and_lowercased_and_nothing_else():
    assert hashing.normalize_email("  Amina@Example.COM ") == "amina@example.com"
    # NOT canonicalised: gmail dots and plus-tags are part of the address as far as every
    # ad platform is concerned. "Helpfully" stripping them produces a hash that matches
    # nothing, which is the single most common way a Meta integration reports 0% match.
    assert hashing.normalize_email("a.m.i.n.a+shop@gmail.com") == "a.m.i.n.a+shop@gmail.com"


def test_hashed_email_is_sha256_of_the_normalised_form():
    assert hashing.hashed_email(" Amina@Example.com ") == _sha("amina@example.com")


def test_phone_keeps_the_country_code_and_drops_everything_else():
    assert hashing.normalize_phone("+234 801 234 5678") == "2348012345678"
    assert hashing.normalize_phone("+44-7700-900123") == "447700900123"


def test_a_phone_without_a_country_code_is_dropped_not_guessed():
    """A local number matches a DIFFERENT person in another country, or nobody. Sending
    nothing is strictly better than sending a confident wrong answer."""
    assert hashing.normalize_phone("08012345678") == ""
    assert hashing.normalize_phone("0801 234 5678") == ""
    assert hashing.hashed_phone("08012345678") == ""


def test_phone_lengths_outside_e164_are_refused():
    assert hashing.normalize_phone("+1234") == ""              # too short
    assert hashing.normalize_phone("+1234567890123456") == ""  # too long


def test_names_fold_accents_but_emails_do_not():
    assert hashing.normalize_name("Adéwálé") == "adewale"
    assert hashing.normalize_name("O'Brien-Smith") == "obriensmith"
    # The same fold applied to an email would hash an address that does not exist.
    assert hashing.normalize_email("adéwálé@x.com") == "adéwálé@x.com"


def test_city_and_state_keep_digits_and_lose_punctuation():
    assert hashing.normalize_city("Lekki Phase 1") == "lekkiphase1"
    assert hashing.normalize_state("Akwa Ibom") == "akwaibom"


def test_zip_truncates_a_us_plus_four_but_keeps_a_uk_postcode():
    assert hashing.normalize_zip("90210-1234") == "90210"
    assert hashing.normalize_zip("SW1A 1AA") == "sw1a1aa"


def test_country_must_be_two_letters():
    assert hashing.normalize_country(" ng ") == "ng"
    assert hashing.normalize_country("Nigeria") == ""


def test_empty_in_empty_out_rather_than_a_hash_of_nothing():
    """A hash of "" is a perfectly valid hash, and sending it asserts we know an
    identifier we do not have. Every platform scores that as a FAILED match rather than
    an absent one, which is worse than saying nothing."""
    assert hashing.sha256_hex("") == ""
    assert hashing.hashed_email(None) == ""
    assert hashing.hashed_name("") == ""
