"""The guard tests are adversarial on purpose.

`infra/deploy/backup.sh` documents that the Django container holds the credential that
writes `backups/` — the only off-box copies of the database. Every delete and copy-source
in this feature goes through `assert_incoming`, so these cases are the seatbelt.
"""
import pytest

from apps.cms.s3_uploads import (
    INCOMING_PREFIX, LIBRARY_PREFIX, UnsafeKeyError,
    assert_incoming, library_key_for, new_incoming_key,
)


@pytest.mark.parametrize(
    "key",
    [
        "backups/postgres/toke-20260810-023001.sql.gz",
        "backups/",
        "catalog/library/existing.mp4",
        "catalog/cms-banners/hero.jpg",
        "incoming/../backups/steal.sql.gz",
        "incoming/../../etc/passwd",
        "/incoming/abc.mp4",
        "Incoming/abc.mp4",
        "",
        "   ",
    ],
)
def test_assert_incoming_refuses_anything_outside_the_quarantine(key):
    with pytest.raises(UnsafeKeyError):
        assert_incoming(key)


def test_assert_incoming_refuses_none():
    with pytest.raises(UnsafeKeyError):
        assert_incoming(None)  # type: ignore[arg-type]


def test_assert_incoming_allows_a_minted_key():
    key = new_incoming_key("mp4")
    assert assert_incoming(key) == key


def test_new_incoming_key_shape():
    key = new_incoming_key("mp4")
    assert key.startswith(INCOMING_PREFIX) and key.endswith(".mp4")
    # No client string anywhere in it: uuid4 hex + extension only.
    stem = key[len(INCOMING_PREFIX):-len(".mp4")]
    assert len(stem) == 32 and all(c in "0123456789abcdef" for c in stem)
    assert new_incoming_key("mp4") != key  # unique per call


def test_new_incoming_key_refuses_unknown_containers():
    with pytest.raises(UnsafeKeyError):
        new_incoming_key("mov")
    with pytest.raises(UnsafeKeyError):
        new_incoming_key("../../evil")


def test_library_key_is_deterministic():
    """Finalize must be idempotent, which means the destination cannot be random."""
    key = new_incoming_key("webm")
    assert library_key_for(key) == library_key_for(key)
    assert library_key_for(key).startswith(LIBRARY_PREFIX)
    assert library_key_for(key).endswith(".webm")


def test_library_key_refuses_a_non_incoming_source():
    with pytest.raises(UnsafeKeyError):
        library_key_for("backups/postgres/dump.sql.gz")
