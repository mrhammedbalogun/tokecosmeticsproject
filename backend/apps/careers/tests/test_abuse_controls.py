"""The controls that stand between a public form with a file upload and the internet.

Kept in its own file because every test here needs the throttles ON, and every test in
`test_public_api.py` needs them off — mixing the two makes the eleventh test in a file
fail for reasons that have nothing to do with what it asserts.
"""
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.careers.factories import posting
from apps.careers.models import JobApplication

pytestmark = pytest.mark.django_db

TICKET = "/api/v1/careers/uploads/"


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture(autouse=True)
def _clear_throttle_buckets():
    """SimpleRateThrottle counts in the cache, which is process-global."""
    cache.clear()
    yield
    cache.clear()


def test_minting_upload_tickets_is_rate_limited(client):
    """The endpoint that CREATES OBJECTS in the bucket holding the database backups."""
    allowed = 0
    for _ in range(12):
        response = client.post(TICKET, {"filename": "CV.pdf"}, format="json")
        if response.status_code == 429:
            break
        allowed += 1
    assert allowed == 6, f"expected the 6/min cap, got {allowed}"


def test_applying_is_rate_limited(client):
    job = posting()
    refused = False
    for _ in range(14):
        response = client.post(
            f"/api/v1/careers/jobs/{job.slug}/apply/",
            {"full_name": "Ada Obi", "email": "ada@example.com",
             "phone": "+2348023900964", "upload_key": "incoming/nope.pdf",
             "resume_filename": "CV.pdf"},
            format="json",
        )
        if response.status_code == 429:
            refused = True
            break
    assert refused, "the apply endpoint accepted 14 submissions in a minute"


def test_turnstile_gates_the_upload_ticket_when_a_secret_is_configured(client, settings):
    """The project-wide fixture clears the secret for the whole suite; this opts back in.

    Verified HERE and not on the apply call on purpose: the ticket is a write
    authorisation into the bucket, so it is the thing a bot must pay for before it can do
    anything at all. Gating the submit instead would mean handing out write tickets to
    unauthenticated callers and hoping they come back.
    """
    settings.TURNSTILE_SECRET = "secret-that-will-never-be-called"
    response = client.post(TICKET, {"filename": "CV.pdf"}, format="json")
    assert response.status_code == 403
    assert "Human verification" in response.data["detail"]


def test_the_direct_upload_endpoint_refuses_itself_once_a_bucket_exists(client, settings):
    """The one function in this feature that would let bytes into the API container in
    production. The guard lives in the storage module so it survives a refactor of the
    view."""
    from apps.careers import resume_storage
    from apps.cms.s3_uploads import UnsafeKeyError

    settings.AWS_STORAGE_BUCKET_NAME = "toke-assets"
    with pytest.raises(UnsafeKeyError):
        resume_storage.store_direct_upload("incoming/x.pdf", object())


def test_a_resume_key_outside_its_prefix_can_never_be_deleted():
    """The bucket also holds `backups/postgres/`. This is the seatbelt."""
    from apps.careers import resume_storage
    from apps.cms.s3_uploads import UnsafeKeyError

    for key in ("backups/postgres/2026-09-20.dump",
                "recruitment/resumes/../../backups/x.dump",
                "catalog/library/logo.png",
                ""):
        with pytest.raises(UnsafeKeyError):
            resume_storage.delete(key)


def test_nothing_is_stored_when_the_application_body_is_junk(client):
    job = posting()
    response = client.post(
        f"/api/v1/careers/jobs/{job.slug}/apply/", {}, format="json"
    )
    assert response.status_code == 400
    assert not JobApplication.objects.exists()
    # Every required field is named, so the form can paint all of them at once rather
    # than making the applicant discover them one submit at a time.
    assert set(response.data) >= {"full_name", "email", "phone", "upload_key",
                                  "resume_filename"}


def test_the_upload_ticket_key_is_server_minted_and_unguessable(client):
    """A client-supplied key would let one applicant overwrite another's upload."""
    first = client.post(TICKET, {"filename": "CV.pdf"}, format="json").data
    second = client.post(TICKET, {"filename": "CV.pdf"}, format="json").data
    assert first["key"] != second["key"]
    assert first["key"].startswith("incoming/")
    # 32 hex characters of uuid4, and nothing from the filename we were given.
    assert "CV" not in first["key"]
    assert len(first["key"].removeprefix("incoming/").removesuffix(".pdf")) == 32


def test_an_oversized_file_is_refused_before_a_ticket_is_minted(client):
    response = client.post(
        TICKET, {"filename": "CV.pdf", "size": 6 * 1024 * 1024}, format="json"
    )
    assert response.status_code == 400
    assert "5MB" in response.data["size"][0]
