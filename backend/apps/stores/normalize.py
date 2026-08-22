"""Text normalisation for the store directory — the one place a store's identity
is reduced to a comparable key.

Two keys, both derived and both stored (`StoreLocation.name_key` /
`address_key`), because they are compared in SQL: a duplicate check that had to
normalise in Python would have to load every row in the LGA first, and the
database's unique index could not exist at all.

WHY NORMALISE AT ALL, rather than comparing the raw strings. The rows are typed
by hand from a WhatsApp message or a spreadsheet, so "12, Hassan Balogun St."
and "12 Hassan Balogun Street" are the same shop and neither spelling is more
correct than the other. Casefold + punctuation-strip + whitespace-collapse
catches the overwhelming majority of that; a common street-word expansion
("st" -> "street") catches the rest of the cheap wins. Anything beyond that
(trigram similarity, geocoding) is a real matching problem and is deliberately
left to the SOFT duplicate warning in `services.py`, which a human resolves.

`slugify_name` is the public URL vocabulary: "Federal Capital Territory" ->
"federal-capital-territory". It is applied to `core.Region.name`, which is
seeded reference data — see `services.resolve_place` for what happens when two
names in one scope slugify the same way, and `tests/test_slugs.py` for the
assertion that they currently do not.
"""

from __future__ import annotations

import re
import unicodedata

from django.utils.text import slugify

# Everything that is not a letter, a digit or a space. Kept as a character class
# rather than `str.isalnum()` so accented letters survive to the fold below.
_NON_ALNUM = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")

# Street-word spellings that mean the same thing. Applied whole-word only, after
# punctuation has gone, so "st" in "st helens" is caught too — which is wrong for
# a saint and right for a street, and the cost of being wrong is a duplicate
# WARNING a human dismisses, never a refused save.
_STREET_WORDS = {
    "st": "street",
    "str": "street",
    "rd": "road",
    "ave": "avenue",
    "av": "avenue",
    "cl": "close",
    "cres": "crescent",
    "dr": "drive",
    "hwy": "highway",
    "jct": "junction",
    "opp": "opposite",
    "no": "number",
    "shp": "shop",
    "bldg": "building",
    "est": "estate",
    "expy": "expressway",
    "exp": "expressway",
}


def _fold(value: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _NON_ALNUM.sub(" ", text.casefold())
    return _SPACES.sub(" ", text).strip()


def name_key(value: str) -> str:
    """The comparable form of a store name. "Toke Ogudu Store" -> "toke ogudu store"."""
    return _fold(value)


def address_key(value: str) -> str:
    """The comparable form of a street address, with street words expanded.

    "12, Hassan Balogun St., Ikotun" -> "12 hassan balogun street ikotun".
    """
    words = _fold(value).split()
    return " ".join(_STREET_WORDS.get(word, word) for word in words)


def phone_key(value: str) -> str:
    """Digits only, so "+2348023900964" and "0802 390 0964" can be compared.

    Deliberately NOT E.164: the stored value already is, but a duplicate check
    should also catch the row somebody typed without a country code before the
    serializer rejected it, and the last-nine-digits comparison in `services.py`
    is what does that.
    """
    return re.sub(r"\D", "", value or "")


def slugify_name(value: str) -> str:
    """The public URL form of a country/state/area name. Never stored."""
    return slugify(value or "")
