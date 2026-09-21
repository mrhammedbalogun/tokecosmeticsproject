"""The PRODUCTION storage path, which no other test in this app reaches.

Every other careers test runs with no bucket configured, so it exercises the filesystem
fallback. That is deliberate — it keeps the suite free of AWS — but it leaves the branch
that actually runs in production unexecuted, and the properties that matter most are all
on that branch: the key a presigned ticket pins, the copy that must not carry the
client's Content-Type, the delete that must never reach `backups/postgres/`.

boto3 is mocked at the client, not stubbed at our own functions: these tests assert the
ARGUMENTS we send to S3, because those arguments ARE the security controls.
"""
from unittest.mock import MagicMock, patch

import pytest

from apps.careers import resume_storage
from apps.cms.s3_uploads import UnsafeKeyError


@pytest.fixture
def s3(settings):
    settings.AWS_STORAGE_BUCKET_NAME = "toke-assets"
    settings.AWS_S3_REGION_NAME = "eu-west-1"
    client = MagicMock()
    client.generate_presigned_post.return_value = {
        "url": "https://toke-assets.s3.eu-west-1.amazonaws.com/",
        "fields": {"key": "incoming/x.pdf"},
    }
    client.generate_presigned_url.return_value = "https://signed.example/cv.pdf?sig=abc"
    with patch("apps.cms.s3_uploads._client", return_value=client):
        yield client


def test_the_upload_ticket_pins_the_key_exactly_and_bounds_the_size(s3):
    ticket = resume_storage.new_ticket("Ada Obi CV.pdf")
    assert ticket["mode"] == "s3"

    conditions = s3.generate_presigned_post.call_args.kwargs["Conditions"]
    key = s3.generate_presigned_post.call_args.kwargs["Key"]

    # EXACT match, never `starts-with`: a prefix condition would let the holder of one
    # ticket write anywhere under `incoming/`.
    assert {"key": key} in conditions
    assert ["content-length-range", 1, resume_storage.MAX_RESUME_BYTES] in conditions
    # And the type is pinned too, because this ticket is handed to an anonymous member
    # of the public.
    assert {"Content-Type": "application/pdf"} in conditions
    # Nothing in the key came from the filename we were given.
    assert key.startswith("incoming/") and key.endswith(".pdf")
    assert "Ada" not in key


def test_the_copy_replaces_the_metadata_and_pins_the_source_etag(s3):
    s3.head_object.return_value = {"ContentLength": 59, "ETag": '"abc123"'}
    s3.get_object.return_value = {"Body": MagicMock(read=lambda: b"%PDF-1.4 hello")}

    key, size, content_type = resume_storage.finalize("incoming/x.pdf", "CV.pdf")

    assert key == "recruitment/resumes/x.pdf"
    assert (size, content_type) == (59, "application/pdf")

    copy = s3.copy_object.call_args.kwargs
    # Without this the ticket holder could swap the bytes between the sniff and the copy.
    assert copy["CopySourceIfMatch"] == "abc123"
    # Without this S3 carries over the CLIENT's Content-Type — handing back the
    # "served as active content" problem the sniff exists to prevent.
    assert copy["MetadataDirective"] == "REPLACE"
    assert copy["ContentType"] == "application/pdf"
    # A stranger's CV must not be cached by anything, anywhere. The bucket-wide default
    # is `public, max-age=86400`, which is right for a product photo and wrong for this.
    assert copy["CacheControl"] == "private, no-store"
    # Quarantine emptied.
    s3.delete_object.assert_called_once()


def test_a_refused_file_is_discarded_and_never_copied(s3):
    s3.head_object.return_value = {"ContentLength": 64, "ETag": '"abc123"'}
    s3.get_object.return_value = {"Body": MagicMock(read=lambda: b"MZ\x90\x00 not a pdf")}

    with pytest.raises(resume_storage.ResumeRejected):
        resume_storage.finalize("incoming/x.pdf", "CV.pdf")

    s3.copy_object.assert_not_called()
    s3.delete_object.assert_called_once()


def test_the_download_url_is_short_lived_private_and_rfc5987_named(s3):
    url = resume_storage.download_url(
        "recruitment/resumes/x.pdf", filename="Adeyemí Òkè - Sales.pdf", inline=False
    )
    assert url == "https://signed.example/cv.pdf?sig=abc"

    call = s3.generate_presigned_url.call_args
    assert call.kwargs["ExpiresIn"] == 60
    params = call.kwargs["Params"]
    assert params["ResponseCacheControl"] == "private, no-store"
    disposition = params["ResponseContentDisposition"]
    assert disposition.startswith("attachment; ")
    # Both halves: the ASCII fallback for old clients, the encoded real name for the rest.
    assert "filename*=UTF-8''" in disposition
    assert "%C3%AD" in disposition


def test_inline_is_a_separate_disposition_so_a_pdf_can_be_read_in_a_tab(s3):
    resume_storage.download_url(
        "recruitment/resumes/x.pdf", filename="cv.pdf", inline=True
    )
    params = s3.generate_presigned_url.call_args.kwargs["Params"]
    assert params["ResponseContentDisposition"].startswith("inline; ")


def test_delete_reaches_only_the_resume_prefix(s3):
    resume_storage.delete("recruitment/resumes/x.pdf")
    assert s3.delete_object.call_args.kwargs["Key"] == "recruitment/resumes/x.pdf"

    # THE BUCKET ALSO HOLDS `backups/postgres/` — the only off-box copies of the database.
    s3.delete_object.reset_mock()
    for key in ("backups/postgres/2026-09-20.dump",
                "recruitment/resumes/../../backups/x.dump",
                "catalog/library/logo.png"):
        with pytest.raises(UnsafeKeyError):
            resume_storage.delete(key)
    s3.delete_object.assert_not_called()


def test_finalize_refuses_a_key_outside_quarantine_before_touching_s3(s3):
    with pytest.raises(UnsafeKeyError):
        resume_storage.finalize("recruitment/resumes/someone-elses.pdf", "CV.pdf")
    s3.head_object.assert_not_called()
    s3.get_object.assert_not_called()


def test_an_object_larger_than_the_cap_is_refused_even_if_the_policy_let_it_through(s3):
    """The presigned policy refuses this before the object exists. Checked anyway — "the
    policy stopped it" is a claim about infrastructure, and this is where it is cheap to
    keep honest."""
    s3.head_object.return_value = {
        "ContentLength": resume_storage.MAX_RESUME_BYTES + 1, "ETag": '"abc"',
    }
    with pytest.raises(resume_storage.ResumeRejected, match="5MB"):
        resume_storage.finalize("incoming/x.pdf", "CV.pdf")
    s3.copy_object.assert_not_called()


def test_direct_upload_is_refused_outright_once_a_bucket_exists(s3):
    """The one function that would let bytes into the API container in production."""
    with pytest.raises(UnsafeKeyError):
        resume_storage.store_direct_upload("incoming/x.pdf", object())
