"""Command-level tests for extract_wp_catalog that don't need a real MariaDB.

Pure attachment-collection logic used to be tested here but has moved to
apps/migration_wp/tests/test_transform.py alongside collect_attachment_ids,
which now lives in transform.py.
"""
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.migration_wp import wp_reader


def test_bad_out_path_fails_before_any_connection_attempt(tmp_path):
    """A typo in --out must be caught before the live DB is ever touched.

    `blocking_file` stands in for a path segment that can never be turned
    into a directory (it's already a file), so no ancestor of --out can be
    created. wp_connection is mocked so the test can assert it is never
    called — proving the validation genuinely happens first, not just that
    the command fails eventually.
    """
    blocking_file = tmp_path / "not_a_dir"
    blocking_file.write_text("x", encoding="utf-8")
    bad_out = blocking_file / "subdir" / "artifact.json"

    with mock.patch.object(wp_reader, "wp_connection") as mock_wp_connection:
        with pytest.raises(CommandError):
            call_command("extract_wp_catalog", f"--out={bad_out}")
        mock_wp_connection.assert_not_called()


def test_good_out_path_passes_validation_and_reaches_the_connection(tmp_path):
    """The inverse check: a legitimately writable --out must NOT be rejected.

    wp_connection is mocked to raise a sentinel so this test doesn't need a
    real database — reaching that mock at all proves validation let a good
    path through.
    """
    good_out = tmp_path / "new_subdir" / "artifact.json"

    with mock.patch.object(wp_reader, "wp_connection", side_effect=RuntimeError("sentinel")):
        with pytest.raises(RuntimeError, match="sentinel"):
            call_command("extract_wp_catalog", f"--out={good_out}")
