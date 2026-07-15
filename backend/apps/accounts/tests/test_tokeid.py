import re

from apps.accounts.models import TOKE_ID_ALPHABET, generate_toke_id


def test_toke_id_shape():
    tid = generate_toke_id()
    assert tid.startswith("TK-")
    assert len(tid) == 9
    assert re.fullmatch(f"TK-[{TOKE_ID_ALPHABET}]{{6}}", tid)


def test_toke_id_alphabet_excludes_ambiguous():
    for ch in "01OIL":
        assert ch not in TOKE_ID_ALPHABET
