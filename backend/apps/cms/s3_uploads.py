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
