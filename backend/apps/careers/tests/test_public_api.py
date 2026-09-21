"""The public careers board and the application flow, over real HTTP.

The properties under test are the three the design rests on:

1. **Nothing unpublished leaks.** A draft or archived role does not exist publicly, and
   a closed one is visible but un-appliable.
2. **The response to a successful application never varies.** Applying twice, applying
   after somebody else applied, applying into a honeypot — all 201, all the same body.
   That is the anti-enumeration property, and it is the one a well-meaning refactor
   ("surely we should tell them they already applied?") would quietly remove.
3. **Only files that ARE what they claim reach the resume prefix.**
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.careers.factories import (
    DOC_BYTES,
    DOCX_BYTES,
    EXE_BYTES,
    PDF_BYTES,
    posting,
)
from apps.careers.models import JobApplication

pytestmark = pytest.mark.django_db

JOBS = "/api/v1/careers/jobs/"
TICKET = "/api/v1/careers/uploads/"
DIRECT = "/api/v1/careers/uploads/direct/"


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture(autouse=True)
def _no_throttling(settings):
    """The rates are asserted in `test_abuse_controls.py`, once. Leaving them on for the
    whole file would make every test order-dependent — the eleventh application in a file
    would 429 for reasons that have nothing to do with what it is testing."""
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
            "careers_upload": None,
            "careers_apply": None,
        },
    }


def upload(client, content: bytes, filename="CV.pdf") -> str:
    """Walk the real two-step upload and return the quarantine key."""
    ticket = client.post(TICKET, {"filename": filename}, format="json")
    assert ticket.status_code == 201, ticket.data
    key = ticket.data["key"]
    stored = client.post(
        DIRECT,
        {"key": key, "file": SimpleUploadedFile(filename, content)},
        format="multipart",
    )
    assert stored.status_code == 201, stored.data
    return key


def apply_body(key, filename="CV.pdf", **overrides):
    body = {
        "full_name": "Ada Obi",
        "email": "ada@example.com",
        "phone": "+2348023900964",
        "upload_key": key,
        "resume_filename": filename,
    }
    body.update(overrides)
    return body


# --- what the board shows ---------------------------------------------------


def test_the_board_lists_open_and_closed_roles_but_never_drafts(client):
    posting("Operations Manager")
    posting("Digital Marketing Officer", status="closed")
    posting("Secret Role", status="draft")

    titles = [row["title"] for row in client.get(JOBS).data]
    assert titles == ["Operations Manager", "Digital Marketing Officer"]


def test_a_closed_role_is_listed_but_not_accepting(client):
    """The badge case. A role that vanishes the moment it is filled makes the candidate
    who bookmarked it believe the site broke."""
    posting("Digital Marketing Officer", status="closed")
    row = client.get(JOBS).data[0]
    assert row["status"] == "closed"
    assert row["is_accepting"] is False


def test_an_archived_role_is_gone_from_the_board_and_404s_by_slug(client):
    job = posting("Withdrawn Role")
    from django.utils import timezone

    job.archived_at = timezone.now()
    job.save(update_fields=["archived_at"])

    assert client.get(JOBS).data == []
    assert client.get(f"{JOBS}{job.slug}/").status_code == 404


def test_a_role_past_its_closing_date_stops_accepting_without_anybody_clicking(client):
    from datetime import timedelta

    from django.utils import timezone

    job = posting("Expiring Role")
    # Set past the deadline directly: the serializer refuses a past date on write, which
    # is the point — this state is only reachable by time passing.
    job.closes_at = timezone.now() - timedelta(hours=1)
    job.save(update_fields=["closes_at"])

    row = client.get(f"{JOBS}{job.slug}/").data
    assert row["is_accepting"] is False


def test_locations_ride_along_so_the_form_can_offer_them(client):
    posting(locations=["Alimosho, Lagos", "Enugu"])
    row = client.get(JOBS).data[0]
    assert [loc["label"] for loc in row["locations"]] == ["Alimosho, Lagos", "Enugu"]


# --- applying ---------------------------------------------------------------


def test_an_application_is_stored_with_the_email_lowercased_and_the_phone_e164(client):
    job = posting(locations=["Alimosho, Lagos"])
    key = upload(client, PDF_BYTES)
    location = job.locations.first()

    response = client.post(
        f"{JOBS}{job.slug}/apply/",
        apply_body(key, email="ADA.Obi@Example.COM", phone="0802 390 0964",
                   location=location.pk),
        format="json",
    )
    # The phone is rejected without a country code — that is `core.phones`' rule and this
    # form obeys it like every other.
    assert response.status_code == 400
    assert "country code" in response.data["phone"][0]

    response = client.post(
        f"{JOBS}{job.slug}/apply/",
        apply_body(key, email="ADA.Obi@Example.COM", location=location.pk),
        format="json",
    )
    assert response.status_code == 201
    application = JobApplication.objects.get()
    assert application.email == "ada.obi@example.com"
    assert application.phone == "+2348023900964"
    # Snapshots, so a later retitle or a removed city cannot rewrite history.
    assert application.job_title == job.title
    assert application.location_label == "Alimosho, Lagos"


def test_the_cv_lands_in_the_resume_prefix_and_leaves_quarantine(client):
    job = posting()
    key = upload(client, PDF_BYTES)
    client.post(f"{JOBS}{job.slug}/apply/", apply_body(key), format="json")

    application = JobApplication.objects.get()
    assert application.resume_key.startswith("recruitment/resumes/")
    assert application.resume_content_type == "application/pdf"

    from django.core.files.storage import default_storage

    assert default_storage.exists(application.resume_key)
    assert not default_storage.exists(key)  # quarantine emptied


@pytest.mark.parametrize(
    "content,filename",
    [(PDF_BYTES, "CV.pdf"), (DOC_BYTES, "CV.doc"), (DOCX_BYTES, "CV.docx")],
)
def test_every_accepted_document_type_gets_through(client, content, filename):
    job = posting()
    key = upload(client, content, filename)
    response = client.post(
        f"{JOBS}{job.slug}/apply/", apply_body(key, filename), format="json"
    )
    assert response.status_code == 201, response.data


def test_an_executable_renamed_to_pdf_is_refused_and_never_stored(client):
    """The case an extension allow-list misses entirely."""
    job = posting()
    key = upload(client, EXE_BYTES, "payload.pdf")
    response = client.post(
        f"{JOBS}{job.slug}/apply/", apply_body(key, "payload.pdf"), format="json"
    )
    assert response.status_code == 400
    assert "not a valid PDF" in response.data["resume"][0]
    assert not JobApplication.objects.exists()

    from django.core.files.storage import default_storage

    # And the refused upload is discarded immediately rather than left to age out.
    assert not default_storage.exists(key)


def test_a_zip_that_is_not_a_docx_is_refused(client):
    job = posting()
    not_a_docx = b"PK\x03\x04" + b"\x00" * 22 + b"\x08\x00\x00\x00" + b"evil.exe" + b"\x00" * 32
    key = upload(client, not_a_docx, "CV.docx")
    response = client.post(
        f"{JOBS}{job.slug}/apply/", apply_body(key, "CV.docx"), format="json"
    )
    assert response.status_code == 400


def test_an_unsupported_extension_never_gets_a_ticket(client):
    """Refused at the first step, so no object is ever created for it."""
    response = client.post(TICKET, {"filename": "cv.exe"}, format="json")
    assert response.status_code == 400
    assert "PDF, DOC or DOCX" in response.data["filename"][0]


def test_a_key_outside_the_quarantine_prefix_is_refused(client):
    """Nothing a real form produces. The guard exists because the same bucket holds the
    database backups."""
    job = posting()
    response = client.post(
        f"{JOBS}{job.slug}/apply/",
        apply_body("backups/postgres/2026-09-20.dump"),
        format="json",
    )
    assert response.status_code == 400
    assert not JobApplication.objects.exists()


# --- the anti-enumeration property ------------------------------------------


def test_applying_twice_is_indistinguishable_from_applying_once(client):
    """THE PROPERTY. If this test ever fails because somebody added a helpful "you have
    already applied" message, the message is the bug: it confirms to whoever typed the
    address that its owner is job-hunting here."""
    job = posting()
    first = client.post(
        f"{JOBS}{job.slug}/apply/", apply_body(upload(client, PDF_BYTES)), format="json"
    )
    second = client.post(
        f"{JOBS}{job.slug}/apply/", apply_body(upload(client, PDF_BYTES)), format="json"
    )
    assert first.status_code == second.status_code == 201
    assert first.data == second.data


def test_a_second_application_replaces_the_first_while_it_is_untouched(client):
    """The candidate's own fix for attaching the wrong CV."""
    job = posting()
    client.post(
        f"{JOBS}{job.slug}/apply/",
        apply_body(upload(client, PDF_BYTES), cover_letter="first draft"),
        format="json",
    )
    client.post(
        f"{JOBS}{job.slug}/apply/",
        apply_body(upload(client, PDF_BYTES), cover_letter="better draft"),
        format="json",
    )

    application = JobApplication.objects.get()   # ONE row
    assert application.cover_letter == "better draft"
    assert application.submission_count == 2


def test_the_old_cv_is_deleted_when_an_application_is_replaced(client):
    from django.core.files.storage import default_storage

    job = posting()
    client.post(
        f"{JOBS}{job.slug}/apply/", apply_body(upload(client, PDF_BYTES)), format="json"
    )
    first_key = JobApplication.objects.get().resume_key

    client.post(
        f"{JOBS}{job.slug}/apply/", apply_body(upload(client, PDF_BYTES)), format="json"
    )
    second_key = JobApplication.objects.get().resume_key

    assert first_key != second_key
    assert not default_storage.exists(first_key)
    assert default_storage.exists(second_key)


def test_a_resubmission_after_review_makes_a_second_row_instead_of_overwriting(client):
    """Nobody who merely knows an address may destroy a review in progress."""
    job = posting()
    client.post(
        f"{JOBS}{job.slug}/apply/", apply_body(upload(client, PDF_BYTES)), format="json"
    )
    reviewed = JobApplication.objects.get()
    reviewed.status = "shortlisted"
    reviewed.staff_notes = "Strong. Call her."
    reviewed.save()

    response = client.post(
        f"{JOBS}{job.slug}/apply/", apply_body(upload(client, PDF_BYTES)), format="json"
    )
    assert response.status_code == 201
    assert JobApplication.objects.count() == 2
    reviewed.refresh_from_db()
    assert reviewed.status == "shortlisted"
    assert reviewed.staff_notes == "Strong. Call her."
    assert JobApplication.objects.exclude(pk=reviewed.pk).get().is_resubmission is True


# --- the races and the refusals ---------------------------------------------


def test_applying_to_a_role_that_closed_meanwhile_is_a_409(client):
    job = posting()
    key = upload(client, PDF_BYTES)
    job.status = "closed"
    job.save(update_fields=["status"])

    response = client.post(f"{JOBS}{job.slug}/apply/", apply_body(key), format="json")
    assert response.status_code == 409
    assert "no longer accepting" in response.data["detail"]


def test_a_role_with_locations_requires_one_to_be_chosen(client):
    job = posting(locations=["Alimosho, Lagos"])
    response = client.post(
        f"{JOBS}{job.slug}/apply/", apply_body(upload(client, PDF_BYTES)), format="json"
    )
    assert response.status_code == 400
    assert response.data["location"]


def test_a_location_belonging_to_another_role_is_refused(client):
    """Without the parentage check a crafted id files an application under a city the
    role never advertised."""
    job = posting("Sales Representative", locations=["Alimosho, Lagos"])
    other = posting("Operations Manager", locations=["Lagos"])

    response = client.post(
        f"{JOBS}{job.slug}/apply/",
        apply_body(upload(client, PDF_BYTES), location=other.locations.first().pk),
        format="json",
    )
    assert response.status_code == 400
    assert "no longer listed" in response.data["location"][0]


def test_a_role_with_no_locations_ignores_one_sent_anyway(client):
    job = posting("Operations Manager")
    response = client.post(
        f"{JOBS}{job.slug}/apply/",
        apply_body(upload(client, PDF_BYTES), location=999),
        format="json",
    )
    assert response.status_code == 201
    assert JobApplication.objects.get().location is None


def test_applying_to_a_draft_role_404s(client):
    job = posting("Secret Role", status="draft")
    response = client.post(
        f"{JOBS}{job.slug}/apply/", apply_body(upload(client, PDF_BYTES)), format="json"
    )
    assert response.status_code == 404


def test_the_honeypot_answers_201_and_stores_nothing(client):
    """Answering 400 would tell a bot author which hurdle they failed."""
    job = posting()
    response = client.post(
        f"{JOBS}{job.slug}/apply/",
        apply_body(upload(client, PDF_BYTES), website="http://spam.example"),
        format="json",
    )
    assert response.status_code == 201
    assert response.data == {"job_title": job.title}
    assert not JobApplication.objects.exists()


def test_a_cover_letter_longer_than_the_cap_is_refused(client):
    job = posting()
    response = client.post(
        f"{JOBS}{job.slug}/apply/",
        apply_body(upload(client, PDF_BYTES), cover_letter="x" * 5001),
        format="json",
    )
    assert response.status_code == 400
    assert response.data["cover_letter"]


def test_an_empty_upload_is_refused(client):
    job = posting()
    ticket = client.post(TICKET, {"filename": "CV.pdf"}, format="json")
    key = ticket.data["key"]
    client.post(
        DIRECT,
        {"key": key, "file": SimpleUploadedFile("CV.pdf", b"")},
        format="multipart",
    )
    response = client.post(f"{JOBS}{job.slug}/apply/", apply_body(key), format="json")
    assert response.status_code == 400


def test_a_filename_whose_extension_disagrees_with_the_key_is_refused(client):
    """The ".docx bytes, .pdf content-type" shape: the key's extension is what the bytes
    were uploaded under, and a second filename must not redefine it."""
    job = posting()
    key = upload(client, PDF_BYTES, "CV.pdf")
    response = client.post(
        f"{JOBS}{job.slug}/apply/", apply_body(key, "CV.docx"), format="json"
    )
    assert response.status_code == 400
