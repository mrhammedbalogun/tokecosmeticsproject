"""extract_wp_customers — the artifact's shape and, mostly, its file mode.

No MariaDB here: `wp_reader` is stubbed, because what these tests are about is what the
command does with the rows once it has them.
"""

import json
import stat
from contextlib import contextmanager
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.migration_wp import wp_reader

ROWS = [
    {
        "ID": 101,
        "user_email": "ada@example.com",
        "user_pass": "$P$Bsynthetic00000000000000000000",
        "user_login": "ada",
        "display_name": "Ada Okafor",
        "user_registered": "2025-03-01 10:00:00",
    }
]
META = {101: {"first_name": "Ada", "billing_phone": "+2348012345678"}}


@pytest.fixture
def stub_wp(monkeypatch):
    @contextmanager
    def fake_connection():
        yield object()

    monkeypatch.setattr(wp_reader, "wp_connection", fake_connection)
    monkeypatch.setattr(wp_reader, "fetch_customers", lambda conn: ROWS)
    monkeypatch.setattr(wp_reader, "fetch_user_meta", lambda conn, ids: META)


def test_THE_ARTIFACT_IS_0600_BECAUSE_IT_HOLDS_REAL_PASSWORD_HASHES(stub_wp, tmp_path):
    """~977 real password hashes, on a box that is being actively probed and has already
    had one malware incident. The mode is set at CREATE via os.open rather than chmod-ed
    afterwards, so there is no window — however short — where the file is readable by
    every other account on the server."""
    out = tmp_path / "customers-legacy_ng.json"
    call_command("extract_wp_customers", "--store", "legacy_ng", "--out", str(out),
                 stdout=StringIO())

    mode = stat.S_IMODE(out.stat().st_mode)
    assert mode == 0o600, f"artifact is {oct(mode)}, not 0600"


def test_the_artifact_carries_the_store_and_the_rows(stub_wp, tmp_path):
    out = tmp_path / "a.json"
    call_command("extract_wp_customers", "--store", "legacy_intl", "--out", str(out),
                 stdout=StringIO())

    data = json.loads(out.read_text())
    assert data["store"] == "legacy_intl"
    assert data["version"] == 1
    assert [c["ID"] for c in data["customers"]] == [101]
    # Meta is keyed by string, because JSON has no integer keys and the importer looks it
    # up both ways rather than relying on which side got it right.
    assert data["meta"]["101"]["first_name"] == "Ada"


def test_the_operator_is_warned_that_the_file_is_dangerous(stub_wp, tmp_path):
    out = StringIO()
    call_command("extract_wp_customers", "--store", "legacy_ng",
                 "--out", str(tmp_path / "a.json"), stdout=out)
    text = out.getvalue()
    assert "password hashes" in text and "delete it after import" in text


def test_AN_UNKNOWN_STORE_IS_REFUSED_BEFORE_THE_DATABASE_IS_TOUCHED(tmp_path):
    # argparse choices, so this fails without wp_reader being stubbed at all — which is
    # the point: a typo costs nothing rather than a full scan of a live users table.
    with pytest.raises(CommandError):
        call_command("extract_wp_customers", "--store", "legacy_typo",
                     "--out", str(tmp_path / "a.json"))


def test_a_bad_out_path_fails_before_the_database_is_touched(tmp_path):
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x")
    with pytest.raises(CommandError, match="not usable"):
        call_command("extract_wp_customers", "--store", "legacy_ng",
                     "--out", str(not_a_dir / "nested" / "a.json"))


def test_the_extract_and_import_agree_on_the_artifact_shape(stub_wp, tmp_path, db):
    """The seam most likely to rot: extract writes it, import reads it, and nothing else
    checks that they still agree. Round-trips one artifact through both."""
    out = tmp_path / "customers-legacy_ng.json"
    call_command("extract_wp_customers", "--store", "legacy_ng", "--out", str(out),
                 stdout=StringIO())
    call_command("import_customers", str(out), stdout=StringIO())

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(email="ada@example.com")
    assert user.legacy_source == "legacy_ng"
    assert user.first_name == "Ada"
    assert user.legacy_identities.get().wp_user_id == 101
