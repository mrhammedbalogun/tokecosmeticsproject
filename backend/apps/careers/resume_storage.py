"""Where a CV lives between the applicant's browser and the reviewer's screen.

── THE FLOW, AND WHY IT IS THREE STEPS AND NOT ONE ─────────────────────────────

    1. POST /careers/uploads/      -> a presigned S3 POST for ONE key in `incoming/`
    2. the BROWSER uploads to S3   -> bytes never touch the API container
    3. POST /careers/jobs/x/apply/ -> HEAD + ranged GET + sniff + copy + row

The obvious design is one multipart POST to Django. It was rejected on a measured
fact: the API runs THREE sync gunicorn workers (`backend/Dockerfile:49-55`) and they
are the same three that serve checkout. Three concurrent 5 MB uploads plus their
synchronous S3 PUT occupy all of them, and the population allowed to start one is
"anybody on the internet" — a strictly larger set than any other write endpoint in
this project accepts bytes from. `apps/cms/s3_uploads.py` already solved exactly this
for admin video upload; this reuses it rather than inventing a second answer.

The cost is honest and worth naming: a browser that uploads and then never finishes
the form leaves an orphan in `incoming/`, which the bucket's lifecycle rule on that
prefix reclaims. That is the same bargain the video flow already makes.

── THE FILESYSTEM FALLBACK IS NOT A SECOND IMPLEMENTATION OF THE RULES ─────────

With no bucket configured (dev, and every test run) the same three steps happen
against `MEDIA_ROOT` through one extra endpoint that stands in for S3's POST form.
The KEYS, the sniffing, the size cap and the prefix guards are shared code on both
paths — only the four verbs at the bottom of this module (put/head/read/copy/delete)
differ. That split is deliberate: everything a security review cares about is in the
half that does not branch, so a test running on the filesystem is still testing the
production rules.
"""
from __future__ import annotations

import hashlib
import os
import re

from django.conf import settings
from django.core.files.storage import default_storage

from apps.cms.s3_uploads import (
    DOCUMENT_TYPES,
    INCOMING_PREFIX,
    RESUME_PREFIX,
    UnsafeKeyError,
    assert_incoming,
    assert_resume_key,
    mint_document_post,
    new_document_key,
    presign_resume_get,
    publish_resume,
    resume_key_for,
    rfc5987_filename,
)

# 5 MB. A CV that does not fit in 5 MB is a scanned photocopy, and the honest answer to
# one is "send a PDF", not a bigger bucket. Enforced in THREE places on purpose: the
# browser (instant feedback), the presigned policy's `content-length-range` (S3 refuses
# the upload outright, so an oversized body never exists) and `head()` at finalize (the
# ticket's claimed size is not evidence).
MAX_RESUME_BYTES = 5 * 1024 * 1024

# How much of the object the sniffer reads. A document's identifying bytes are in the
# first few, but a .docx's first ZIP member name can sit a little further in, so one
# small ranged GET covers every case without pulling the file into the container.
SNIFF_BYTES = 8192


class ResumeRejected(ValueError):
    """The file is not something we accept. The message is shown to the applicant."""


def uses_s3() -> bool:
    """True when there is a real bucket. The ONE branch point in this module."""
    return bool(settings.AWS_STORAGE_BUCKET_NAME)


# ── the half that does not branch ────────────────────────────────────────────────

_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,8}$")


def extension_for(filename: str) -> str:
    """The lowercased extension of a client-supplied filename, or raise.

    This is the ONLY thing a client filename is ever used for, and the result is
    validated against `DOCUMENT_TYPES` before it reaches a key. The name itself is stored
    for display and never joined onto a path.
    """
    match = _EXT_RE.search((filename or "").strip())
    ext = match.group(0).lower() if match else ""
    if ext not in DOCUMENT_TYPES:
        raise ResumeRejected(
            "Attach your CV as a PDF, DOC or DOCX file."
        )
    return ext


def sniff_document(head: bytes, ext: str) -> str:
    """Identify the REAL bytes, and refuse anything that is not what it claims.

    Returns the Content-Type to store. Raises `ResumeRejected` otherwise.

    An extension allow-list alone stops nothing: `payload.exe` renamed to `cv.pdf` passes
    it. These magic numbers are the actual check, and they run against bytes fetched back
    OUT of the bucket rather than against the upload — the object that gets copied is the
    object that was inspected, which is the property `CopySourceIfMatch` then pins.

    DOCX is the awkward one: it is a ZIP, and so are a great many things that are not
    documents. Requiring the first member to be one of Word's three well-known entries is
    the cheap discriminator — every Word-produced .docx starts with `[Content_Types].xml`,
    and hand-built ones from the common toolchains start with `_rels/` or `word/`.
    """
    if not head:
        raise ResumeRejected("That file is empty. Attach your CV and try again.")

    if ext == ".pdf":
        if not head.startswith(b"%PDF-"):
            raise ResumeRejected("That file is not a valid PDF.")
        return DOCUMENT_TYPES[".pdf"]

    if ext == ".doc":
        # OLE2 compound document — the container Word 97-2003 writes.
        if not head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise ResumeRejected("That file is not a valid Word document.")
        return DOCUMENT_TYPES[".doc"]

    if ext == ".docx":
        if not head.startswith(b"PK\x03\x04"):
            raise ResumeRejected("That file is not a valid Word document.")
        # Local file header: name length at offset 26, the name itself at 30.
        try:
            name_len = int.from_bytes(head[26:28], "little")
            first_member = head[30:30 + name_len]
        except Exception:  # noqa: BLE001 - a truncated header is simply a rejection
            raise ResumeRejected("That file is not a valid Word document.") from None
        if not first_member.startswith((b"[Content_Types].xml", b"_rels/", b"word/")):
            raise ResumeRejected("That file is not a valid Word document.")
        return DOCUMENT_TYPES[".docx"]

    raise ResumeRejected("Attach your CV as a PDF, DOC or DOCX file.")


def new_ticket(filename: str) -> dict:
    """Everything the browser needs to upload one CV, for whichever backend is live.

    The returned `key` is what the apply request carries back. It is server-minted and
    unguessable, which is also what makes it safe to accept from the client at finalize:
    holding it proves nothing more than having been handed it, and every use of it is
    re-validated by `assert_incoming` before anything is read.
    """
    ext = extension_for(filename)
    key = new_document_key(ext)
    content_type = DOCUMENT_TYPES[ext]
    if uses_s3():
        post = mint_document_post(key, MAX_RESUME_BYTES, content_type)
        return {
            "mode": "s3",
            "url": post["url"],
            "fields": post["fields"],
            "key": key,
            "max_bytes": MAX_RESUME_BYTES,
        }
    # Dev/test: one endpoint on this API stands in for the S3 POST form. Same key, same
    # cap, same prefix — see the module docstring.
    return {
        "mode": "direct",
        "url": "/api/v1/careers/uploads/direct/",
        "fields": {"key": key},
        "key": key,
        "max_bytes": MAX_RESUME_BYTES,
    }


def finalize(incoming_key: str, filename: str) -> tuple[str, int, str]:
    """Verify what actually landed and move it out of quarantine.

    Returns `(resume_key, size, content_type)`. Raises `ResumeRejected` for anything an
    applicant can fix, and `UnsafeKeyError` for a key that should never have been sent —
    the two are different because the first is a sentence on a form and the second is a
    security event.
    """
    assert_incoming(incoming_key)
    ext = extension_for(filename)
    # The extension the SERVER put in the key wins over the one the client just sent: the
    # key is the thing the bytes were uploaded under, and letting a second filename
    # redefine it is how ".docx bytes, .pdf content-type" gets stored.
    key_ext = os.path.splitext(incoming_key)[1].lower()
    if key_ext != ext:
        raise ResumeRejected("That upload did not match the file you attached. Try again.")

    size, etag = _head(incoming_key)
    if size <= 0:
        raise ResumeRejected("That file is empty. Attach your CV and try again.")
    if size > MAX_RESUME_BYTES:
        # Reachable only if the ticket policy was somehow bypassed; a real S3 POST refuses
        # this before the object exists. Checked anyway — "the policy stopped it" is a
        # claim about infrastructure, and this file is where the claim is cheap to keep.
        raise ResumeRejected("That file is larger than 5MB. Attach a smaller CV.")

    try:
        content_type = sniff_document(_read_head(incoming_key, SNIFF_BYTES), ext)
    except ResumeRejected:
        # DISCARD A REFUSED UPLOAD IMMEDIATELY. The lifecycle rule on `incoming/` would
        # reclaim it eventually, but "eventually" is a day, and the object we have just
        # refused is by definition the one somebody had a reason to put there. Leaving
        # rejects to age out turns a failed sniff into free storage for whoever keeps
        # failing it.
        _discard(incoming_key)
        raise

    resume_key = _copy_to_resumes(incoming_key, etag, content_type)
    _discard(incoming_key)
    return resume_key, size, content_type


def download_url(key: str, *, filename: str, inline: bool) -> str | None:
    """A short-lived link to one CV, or None when there is no S3 to presign against
    (dev streams the bytes through the API instead — see `admin_views`)."""
    assert_resume_key(key)
    if not uses_s3():
        return None
    return presign_resume_get(key, filename=filename, inline=inline)


def delete(key: str) -> None:
    """Permanently remove one CV. See `s3_uploads.delete_resume` for why this is not
    best-effort."""
    assert_resume_key(key)
    if uses_s3():
        from apps.cms.s3_uploads import delete_resume

        delete_resume(key)
        return
    if default_storage.exists(key):
        default_storage.delete(key)


def delete_quietly(key: str) -> None:
    """`delete`, but a failure is swallowed and logged by the caller's absence of care.

    For the one place it is right: replacing a candidate's own earlier CV. The new file is
    already stored and the row already points at it; failing the request because the OLD
    object could not be removed would lose the application to protect a cleanup.
    """
    try:
        delete(key)
    except Exception:  # noqa: BLE001 - see the docstring
        pass


# ── the four verbs that differ ───────────────────────────────────────────────────

def _head(key: str) -> tuple[int, str]:
    if uses_s3():
        from apps.cms.s3_uploads import head_incoming

        return head_incoming(key)
    if not default_storage.exists(key):
        raise ResumeRejected("That upload was not found. Attach your CV again.")
    with default_storage.open(key, "rb") as handle:
        data = handle.read()
    return len(data), hashlib.md5(data, usedforsecurity=False).hexdigest()


def _read_head(key: str, length: int) -> bytes:
    if uses_s3():
        from apps.cms.s3_uploads import read_incoming_head

        return read_incoming_head(key, length)
    with default_storage.open(key, "rb") as handle:
        return handle.read(length)


def _copy_to_resumes(key: str, etag: str, content_type: str) -> str:
    if uses_s3():
        return publish_resume(key, etag, content_type)
    dest = resume_key_for(key)
    with default_storage.open(key, "rb") as handle:
        saved = default_storage.save(dest, handle)
    # FileSystemStorage uniquifies a name that already exists; S3 does not. Returning what
    # was ACTUALLY written keeps the row pointing at the real file either way.
    return saved


def _discard(key: str) -> None:
    if uses_s3():
        from apps.cms.s3_uploads import discard_incoming

        discard_incoming(key)
        return
    try:
        if default_storage.exists(key):
            default_storage.delete(key)
    except Exception:  # noqa: BLE001 - cleanup must never fail a successful application
        pass


def store_direct_upload(key: str, uploaded_file) -> None:
    """The filesystem stand-in for S3's POST form. DEV AND TEST ONLY.

    Refuses outright when a bucket is configured, rather than trusting the view to
    remember: this is the one function in the feature that would let bytes into the API
    container in production, and a guard in the module that owns it survives a refactor
    of the view that a comment would not.
    """
    if uses_s3():
        raise UnsafeKeyError("Direct upload is not available when S3 is configured.")
    assert_incoming(key)
    if uploaded_file.size > MAX_RESUME_BYTES:
        raise ResumeRejected("That file is larger than 5MB. Attach a smaller CV.")
    default_storage.save(key, uploaded_file)


__all__ = [
    "MAX_RESUME_BYTES",
    "INCOMING_PREFIX",
    "RESUME_PREFIX",
    "ResumeRejected",
    "UnsafeKeyError",
    "delete",
    "delete_quietly",
    "download_url",
    "extension_for",
    "finalize",
    "new_ticket",
    "rfc5987_filename",
    "sniff_document",
    "store_direct_upload",
    "uses_s3",
]
