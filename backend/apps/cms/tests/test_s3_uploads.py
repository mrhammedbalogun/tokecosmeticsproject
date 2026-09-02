"""The guard tests are adversarial on purpose.

`infra/deploy/backup.sh` documents that the Django container holds the credential that
writes `backups/` — the only off-box copies of the database. Every delete and copy-source
in this feature goes through `assert_incoming`, so these cases are the seatbelt.
"""
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from apps.cms.s3_uploads import (
    INCOMING_PREFIX, LIBRARY_PREFIX, UnsafeKeyError,
    assert_incoming, discard_incoming, head_incoming, library_key_for,
    mint_video_post, new_incoming_key, publish_incoming, read_incoming_head,
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


BUCKET = "test-bucket"


@pytest.fixture
def s3(settings):
    """A live-enough S3. `settings` is pytest-django's fixture."""
    settings.AWS_STORAGE_BUCKET_NAME = BUCKET
    settings.AWS_S3_REGION_NAME = "eu-west-1"
    with mock_aws():
        client = boto3.client("s3", region_name="eu-west-1")
        client.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )
        yield client


def test_mint_video_post_pins_the_key_exactly_and_bounds_the_size(s3):
    key = new_incoming_key("mp4")
    ticket = mint_video_post(key, max_bytes=1000)

    assert ticket["key"] == key
    # The key travels as a FIELD, which S3 matches exactly — not a starts-with condition.
    assert ticket["fields"]["key"] == key
    conditions = ticket["_conditions"]
    assert ["content-length-range", 1, 1000] in conditions
    assert not any(
        isinstance(c, list) and c and c[0] == "starts-with" and c[1] == "$key"
        for c in conditions
    ), "a starts-with key condition would let the client choose where bytes land"


def test_mint_video_post_uses_the_regional_virtual_host_url(s3):
    """Found live 2026-08-10: the default client minted `https://<bucket>.s3.amazonaws.com/`
    (global endpoint, SigV2), which S3 307-redirects — and which the admin's CSP
    `connect-src` (pinned to the eu-west-1 host) blocks before the request even leaves
    the browser. The ticket URL must be the exact host the CSP allows."""
    ticket = mint_video_post(new_incoming_key("mp4"), max_bytes=1000)
    assert ticket["url"].startswith(f"https://{BUCKET}.s3.eu-west-1.amazonaws.com"), ticket["url"]


def test_head_incoming_returns_real_size_and_etag(s3):
    key = new_incoming_key("mp4")
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"x" * 1234)

    size, etag = head_incoming(key)
    assert size == 1234
    assert etag and '"' not in etag  # normalised, ready for CopySourceIfMatch


def test_read_incoming_head_reads_only_the_front(s3):
    key = new_incoming_key("mp4")
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"HEAD" + b"z" * 500_000)

    head = read_incoming_head(key, length=16)
    assert head.startswith(b"HEAD")
    assert len(head) == 16, "a ranged read must not pull the whole object"


def test_every_s3_helper_refuses_a_backups_key(s3):
    for fn in (head_incoming, read_incoming_head):
        with pytest.raises(UnsafeKeyError):
            fn("backups/postgres/dump.sql.gz")
    with pytest.raises(UnsafeKeyError):
        mint_video_post("backups/postgres/dump.sql.gz", max_bytes=10)


def test_publish_copies_into_the_library_and_sets_our_own_content_type(s3):
    key = new_incoming_key("mp4")
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"\x00\x00\x00\x20ftypisom",
                  ContentType="text/html")  # the client lied
    _, etag = head_incoming(key)

    dest = publish_incoming(key, etag=etag, content_type="video/mp4")

    assert dest == library_key_for(key)
    landed = s3.head_object(Bucket=BUCKET, Key=dest)
    assert landed["ContentType"] == "video/mp4", "the client's Content-Type must not survive"
    assert "immutable" in landed["CacheControl"]


def test_publish_is_idempotent(s3):
    key = new_incoming_key("mp4")
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"\x00\x00\x00\x20ftypisom")
    _, etag = head_incoming(key)

    first = publish_incoming(key, etag=etag, content_type="video/mp4")
    second = publish_incoming(key, etag=etag, content_type="video/mp4")
    assert first == second


def test_publish_sends_the_safety_kwargs():
    """Asserted on the CALL, not through moto: the TOCTOU defence must not rest on how
    faithfully a simulator implements conditional copy."""
    key = new_incoming_key("mp4")
    with patch("apps.cms.s3_uploads._client") as client:
        publish_incoming(key, etag="abc123", content_type="video/mp4")
        kwargs = client.return_value.copy_object.call_args.kwargs

    assert kwargs["CopySourceIfMatch"] == "abc123"
    assert kwargs["MetadataDirective"] == "REPLACE"
    assert kwargs["ContentType"] == "video/mp4"
    assert kwargs["Key"] == library_key_for(key)


def test_publish_refuses_a_source_outside_the_quarantine():
    with pytest.raises(UnsafeKeyError):
        publish_incoming("backups/postgres/dump.sql.gz", etag="x", content_type="video/mp4")


def test_discard_refuses_a_backups_key():
    with pytest.raises(UnsafeKeyError):
        discard_incoming("backups/postgres/dump.sql.gz")


def test_discard_survives_an_already_gone_object(s3):
    """Finalize's cleanup must never turn a successful publish into a failed request."""
    discard_incoming(new_incoming_key("mp4"))  # never uploaded; must not raise
