"""Direct-to-S3 video uploads: the ONLY module in this feature that talks to S3.

WHY IT IS ONE MODULE. The bucket holds `backups/postgres/` — the only off-box copies of
the database — and `infra/deploy/backup.sh` documents that the `web` container carries
the credential that writes them. So application code that can call `delete_object` can
delete a database dump. Rather than trust every future call site to check its key, every
delete and every copy-source in this feature passes through `assert_incoming` here.

THE FLOW. `new_incoming_key` mints a key the client never influences; the presigned POST
pins it exactly (not `starts-with`) and bounds the size; the browser uploads to
`incoming/`, which the bucket policy does NOT expose to CloudFront; finalize sniffs the
real bytes and only then copies into `catalog/library/`, where the CDN can see it.
"""
import uuid

import boto3
from botocore.config import Config
from django.conf import settings

from apps.cms.video_sniff import VIDEO_EXTENSIONS

INCOMING_PREFIX = "incoming/"
LIBRARY_PREFIX = "catalog/library/"


class UnsafeKeyError(ValueError):
    """A key that is not inside the quarantine prefix. Never catch this to continue."""


def assert_incoming(key: str) -> str:
    """The seatbelt. Returns the key so callers can write `head(assert_incoming(k))`.

    Rejects traversal (`..`) explicitly: S3 keys are opaque strings and `incoming/../x`
    is a perfectly valid key naming a DIFFERENT object, so prefix-matching alone is not
    enough.
    """
    if not isinstance(key, str) or not key.strip():
        raise UnsafeKeyError("An empty key is never valid.")
    if not key.startswith(INCOMING_PREFIX):
        raise UnsafeKeyError(f"Refusing to touch a key outside {INCOMING_PREFIX!r}: {key!r}")
    if ".." in key:
        raise UnsafeKeyError(f"Refusing a key containing traversal: {key!r}")
    return key


def new_incoming_key(container: str) -> str:
    """`incoming/<uuid4hex>.<ext>` — no part of it comes from the client.

    The extension is looked up from the sniffed/declared CONTAINER, never sliced off a
    filename, so an attacker-chosen suffix cannot ride along inside a key we describe as
    server-generated.
    """
    try:
        ext = VIDEO_EXTENSIONS[container]
    except KeyError:
        raise UnsafeKeyError(f"Not a supported video container: {container!r}") from None
    return f"{INCOMING_PREFIX}{uuid.uuid4().hex}{ext}"


def library_key_for(incoming_key: str) -> str:
    """Where a verified object lands. DETERMINISTIC so finalize is idempotent: calling it
    twice copies to the same key and `get_or_create` finds the same row."""
    assert_incoming(incoming_key)
    return LIBRARY_PREFIX + incoming_key[len(INCOMING_PREFIX):]


# Ticket lifetime. Generous on purpose: the key is pinned into a prefix the CDN cannot
# serve, so a long window costs nothing, while a short one punishes an admin who picks a
# file and takes a phone call.
TICKET_TTL_SECONDS = 30 * 60
# How much of the object finalize reads to identify it. Large enough for any container
# header and the moov/mdat question; small enough to be one quick ranged GET.
SNIFF_BYTES = 262_144


def _client():
    """SigV4 + virtual-host addressing, EXPLICITLY. Left to defaults (measured live
    2026-08-10), the client minted presigned POSTs against the GLOBAL endpoint
    (`https://<bucket>.s3.amazonaws.com/`) with SigV2 fields — S3 answers those with a
    307 to the regional host, and the admin's CSP `connect-src` (pinned to the
    eu-west-1 host) blocks the first hop before it leaves the browser."""
    region = settings.AWS_S3_REGION_NAME
    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=f"https://s3.{region}.amazonaws.com",
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )


def _bucket() -> str:
    return settings.AWS_STORAGE_BUCKET_NAME


def mint_video_post(key: str, max_bytes: int) -> dict:
    """A one-shot S3 POST form for exactly `key`, refusing anything over `max_bytes`.

    Presigned POST rather than PUT specifically for `content-length-range`: a presigned
    PUT can pin the key but cannot bound the body, and this bucket holds the database
    backups — an unbounded write into it is not a risk worth taking for a simpler call.
    """
    assert_incoming(key)
    conditions: list = [
        {"key": key},                          # EXACT match, never starts-with
        ["content-length-range", 1, max_bytes],
    ]
    post = _client().generate_presigned_post(
        Bucket=_bucket(),
        Key=key,
        Fields={"key": key},
        Conditions=conditions,
        ExpiresIn=TICKET_TTL_SECONDS,
    )
    # `_conditions` is echoed back for the tests that pin the policy shape; it is not
    # sent to the browser (the serializer picks the fields it exposes).
    return {"url": post["url"], "fields": post["fields"], "key": key, "_conditions": conditions}


def head_incoming(key: str) -> tuple[int, str]:
    """(size, etag) of what ACTUALLY landed. The ticket's claimed size is not evidence."""
    assert_incoming(key)
    meta = _client().head_object(Bucket=_bucket(), Key=key)
    return int(meta["ContentLength"]), meta["ETag"].strip('"')


def read_incoming_head(key: str, length: int = SNIFF_BYTES) -> bytes:
    """The first `length` bytes, via a ranged GET — never the whole object."""
    assert_incoming(key)
    obj = _client().get_object(Bucket=_bucket(), Key=key, Range=f"bytes=0-{length - 1}")
    return obj["Body"].read()


# Keys are unique forever, so the object at one is immutable by construction.
PUBLISHED_CACHE_CONTROL = "public, max-age=31536000, immutable"


def publish_incoming(key: str, etag: str, content_type: str) -> str:
    """Copy a VERIFIED object into the library prefix. Returns the destination key.

    `CopySourceIfMatch` is the load-bearing argument: the presigned ticket stays valid
    while finalize runs, so without it a holder could replace the bytes between the sniff
    and the copy and publish something we never inspected. With it the copy fails
    atomically instead.

    `MetadataDirective="REPLACE"` is equally load-bearing and easy to omit: without it S3
    copies the SOURCE's metadata, including the Content-Type the client chose — which
    would hand back exactly the "served as active content" problem the sniff exists to
    prevent.
    """
    assert_incoming(key)
    dest = library_key_for(key)
    _client().copy_object(
        Bucket=_bucket(),
        Key=dest,
        CopySource={"Bucket": _bucket(), "Key": key},
        CopySourceIfMatch=etag,
        MetadataDirective="REPLACE",
        ContentType=content_type,
        CacheControl=PUBLISHED_CACHE_CONTROL,
    )
    return dest


def discard_incoming(key: str) -> None:
    """Best-effort cleanup of a quarantined object.

    Never raises for a missing object, and callers must not let a failure here fail the
    request: once the copy has succeeded the upload HAS worked, and the lifecycle rule on
    `incoming/` reclaims anything left behind.
    """
    assert_incoming(key)
    try:
        _client().delete_object(Bucket=_bucket(), Key=key)
    except Exception:  # noqa: BLE001 - cleanup must never mask a successful publish
        pass
