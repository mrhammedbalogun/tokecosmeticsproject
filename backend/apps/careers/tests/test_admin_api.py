"""Careers admin: posting CRUD, the applications surface, and the two rules that guard
personal data.

`test_admin_role_matrix.py` proves WHO may reach these routes. This file proves what
happens once they are in, and in particular:

* a reviewer may change a status and a note and NOTHING ELSE about a candidate;
* deleting an application takes the CV with it;
* editing a posting's locations does not detach the applications that chose them.
"""
import io

import pytest
from django.core.files.storage import default_storage
from rest_framework.test import APIClient

from apps.careers.factories import PDF_BYTES, posting
from apps.careers.models import JobApplication, JobPosting
from apps.catalog.tests.factories_admin import staff_user

pytestmark = pytest.mark.django_db

JOBS = "/api/v1/admin/careers/jobs/"
APPS = "/api/v1/admin/careers/applications/"


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


@pytest.fixture
def manager_client():
    c = APIClient()
    c.force_authenticate(user=staff_user(email="manager@toke.test", role="Manager"))
    return c


def job_payload(**overrides):
    body = {
        "title": "Sales Representative",
        "country": "NG",
        "employment_type": "full_time",
        "workplace_type": "on_site",
        "compensation_text": "Good Pay",
        "summary": "Grow Toke Cosmetics in your city.",
        "description": "<p>What you will be doing.</p>",
        "status": "open",
        "locations": [{"label": "Alimosho, Lagos"}, {"label": "Enugu"}],
    }
    body.update(overrides)
    return body


def application_for(job, **overrides):
    fields = {
        "job": job,
        "job_title": job.title,
        "full_name": "Ada Obi",
        "email": "ada@example.com",
        "phone": "+2348023900964",
        "resume_key": "recruitment/resumes/deadbeef.pdf",
        "resume_original_name": "Ada Obi CV.pdf",
        "resume_content_type": "application/pdf",
        "resume_size": len(PDF_BYTES),
    }
    fields.update(overrides)
    return JobApplication.objects.create(**fields)


# --- postings ---------------------------------------------------------------


def test_a_posting_is_created_with_its_locations_in_one_request(client):
    """Eleven cities in eleven HTTP calls would make a half-saved posting a normal state."""
    response = client.post(JOBS, job_payload(), format="json")
    assert response.status_code == 201, response.data
    job = JobPosting.objects.get()
    assert [loc.label for loc in job.locations.all()] == ["Alimosho, Lagos", "Enugu"]
    assert job.slug == "sales-representative"


def test_a_second_role_with_the_same_title_gets_a_distinct_slug(client):
    client.post(JOBS, job_payload(), format="json")
    client.post(JOBS, job_payload(locations=[]), format="json")
    assert sorted(JobPosting.objects.values_list("slug", flat=True)) == [
        "sales-representative", "sales-representative-2",
    ]


def test_opening_a_role_without_a_description_is_refused(client):
    """A draft may be half-written; that is what a draft is for. The moment it goes
    public it owes the reader something to read."""
    response = client.post(JOBS, job_payload(description=""), format="json")
    assert response.status_code == 400
    assert response.data["description"]

    draft = client.post(
        JOBS, job_payload(description="", status="draft", locations=[]), format="json"
    )
    assert draft.status_code == 201


def test_a_closing_date_in_the_past_is_refused(client):
    from datetime import timedelta

    from django.utils import timezone

    response = client.post(
        JOBS,
        job_payload(closes_at=(timezone.now() - timedelta(days=1)).isoformat()),
        format="json",
    )
    assert response.status_code == 400
    assert "already passed" in response.data["closes_at"][0]


def test_two_locations_with_the_same_name_are_refused(client):
    response = client.post(
        JOBS,
        job_payload(locations=[{"label": "Lagos"}, {"label": " lagos "}]),
        format="json",
    )
    assert response.status_code == 400


def test_editing_a_posting_keeps_the_location_rows_its_applications_point_at(client):
    """DELETE-THEN-RECREATE WOULD NULL EVERY APPLICANT'S CHOSEN CITY. The ids are
    round-tripped so an edit updates in place."""
    job = posting(locations=["Alimosho, Lagos", "Enugu"])
    alimosho = job.locations.first()
    application = application_for(job, location=alimosho, location_label=alimosho.label)

    response = client.patch(
        f"{JOBS}{job.slug}/",
        {"locations": [
            {"id": alimosho.pk, "label": "Alimosho, Lagos"},
            {"label": "Onitsha"},
        ]},
        format="json",
    )
    assert response.status_code == 200, response.data
    application.refresh_from_db()
    assert application.location_id == alimosho.pk
    assert [loc.label for loc in job.locations.all()] == ["Alimosho, Lagos", "Onitsha"]


def test_a_removed_location_leaves_the_application_with_its_snapshot(client):
    """SET_NULL absorbs it, and the label snapshot is what the screen renders — so the
    reviewer can still see where the person applied."""
    job = posting(locations=["Enugu"])
    enugu = job.locations.first()
    application = application_for(job, location=enugu, location_label="Enugu")

    client.patch(f"{JOBS}{job.slug}/", {"locations": []}, format="json")
    application.refresh_from_db()
    assert application.location_id is None
    assert application.location_label == "Enugu"


def test_delete_archives_a_posting_rather_than_removing_it(client):
    job = posting()
    application_for(job)

    assert client.delete(f"{JOBS}{job.slug}/").status_code == 204
    job.refresh_from_db()
    assert job.archived_at is not None
    # The application it protects is untouched — and would have blocked a real delete.
    assert JobApplication.objects.count() == 1


def test_an_archived_posting_is_out_of_the_default_list_and_restores_as_a_draft(client):
    job = posting()
    client.delete(f"{JOBS}{job.slug}/")

    assert client.get(JOBS).data["results"] == [] if isinstance(
        client.get(JOBS).data, dict
    ) else client.get(JOBS).data == []

    restored = client.post(f"{JOBS}{job.slug}/restore/")
    assert restored.status_code == 200
    job.refresh_from_db()
    assert job.archived_at is None
    # Deliberately NOT straight back onto the careers page.
    assert job.status == "draft"


def test_the_postings_list_counts_applications_without_exposing_them(client):
    """A number is not personal data; a list of names is. This screen sits behind
    `careers.manage`, which is not the PII scope."""
    job = posting()
    application_for(job)
    application_for(job, email="bola@example.com")

    row = client.get(JOBS).data
    rows = row["results"] if isinstance(row, dict) else row
    assert rows[0]["application_count"] == 2
    assert "applications" not in rows[0]


# --- applications -----------------------------------------------------------


def test_the_list_carries_no_cover_letter_but_the_detail_does(client):
    """Bulk egress of every candidate's cover letter in one response is exactly what
    `audit_reads` exists to record — so the list simply does not carry it."""
    job = posting()
    application = application_for(job, cover_letter="Why I want this job.")

    row = client.get(APPS).data
    rows = row["results"] if isinstance(row, dict) else row
    assert "cover_letter" not in rows[0]
    assert rows[0]["has_cover_letter"] is True

    detail = client.get(f"{APPS}{application.pk}/").data
    assert detail["cover_letter"] == "Why I want this job."


def test_the_resume_key_is_never_serialised_to_the_admin(client):
    job = posting()
    application = application_for(job)
    detail = client.get(f"{APPS}{application.pk}/").data
    assert "resume_key" not in detail
    assert detail["resume_original_name"] == "Ada Obi CV.pdf"


def test_a_reviewer_may_change_only_the_status_and_the_notes(client):
    """An admin that can silently rewrite an applicant's contact details is an admin
    whose records stop being evidence of what the candidate actually sent."""
    job = posting()
    application = application_for(job)

    response = client.patch(
        f"{APPS}{application.pk}/",
        {"status": "shortlisted", "staff_notes": "Call her.",
         "full_name": "Somebody Else", "email": "attacker@example.com"},
        format="json",
    )
    assert response.status_code == 200
    application.refresh_from_db()
    assert application.status == "shortlisted"
    assert application.staff_notes == "Call her."
    assert application.full_name == "Ada Obi"
    assert application.email == "ada@example.com"


def test_changing_the_status_stamps_the_reviewer_and_a_note_edit_does_not(client):
    job = posting()
    application = application_for(job)

    client.patch(f"{APPS}{application.pk}/", {"status": "in_review"}, format="json")
    application.refresh_from_db()
    first_stamp = application.reviewed_at
    assert first_stamp is not None
    assert application.reviewed_by is not None

    client.patch(f"{APPS}{application.pk}/", {"staff_notes": "typo fix"}, format="json")
    application.refresh_from_db()
    assert application.reviewed_at == first_stamp


def test_deleting_an_application_removes_its_cv_too(client):
    job = posting()
    key = default_storage.save("recruitment/resumes/test-cv.pdf",
                               io.BytesIO(PDF_BYTES))
    application = application_for(job, resume_key=key)

    assert client.delete(f"{APPS}{application.pk}/").status_code == 204
    assert not JobApplication.objects.exists()
    assert not default_storage.exists(key)


def test_a_manager_may_read_and_decide_but_not_delete(manager_client):
    """The inline elevation. A Manager screening candidates should not be able to destroy
    the record of a hiring decision, or the CV behind it."""
    job = posting()
    application = application_for(job)

    assert manager_client.get(f"{APPS}{application.pk}/").status_code == 200
    assert manager_client.patch(
        f"{APPS}{application.pk}/", {"status": "rejected"}, format="json"
    ).status_code == 200
    assert manager_client.delete(f"{APPS}{application.pk}/").status_code == 403
    assert JobApplication.objects.count() == 1


def test_the_cv_download_names_the_file_after_the_candidate_and_the_role(client):
    job = posting("Sales Representative")
    key = default_storage.save("recruitment/resumes/named.pdf",
                               io.BytesIO(PDF_BYTES))
    application = application_for(job, resume_key=key)

    response = client.get(f"{APPS}{application.pk}/resume/")
    assert response.status_code == 200
    # No bucket in tests, so it streams. Either way the name is the assertion.
    assert "Ada Obi - Sales Representative.pdf" in response["Content-Disposition"]
    assert response["Content-Disposition"].startswith("attachment")
    assert response["Cache-Control"] == "private, no-store"

    inline = client.get(f"{APPS}{application.pk}/resume/?disposition=inline")
    assert inline["Content-Disposition"].startswith("inline")


def test_a_non_ascii_candidate_name_survives_the_download_header(client):
    """RFC 5987. Without it "Adeyemí" is mangled by the save dialog."""
    job = posting("Sales Representative")
    key = default_storage.save("recruitment/resumes/utf8.pdf",
                               io.BytesIO(PDF_BYTES))
    application = application_for(job, full_name="Adeyemí Òkè", resume_key=key)

    disposition = client.get(f"{APPS}{application.pk}/resume/")["Content-Disposition"]
    assert "filename*=UTF-8''" in disposition
    assert "Adeyem" in disposition          # the ASCII fallback kept what it could
    assert "%C3%AD" in disposition          # and the real name is percent-encoded


def test_applications_can_be_filtered_by_role_and_status_and_searched_by_phone(client):
    sales = posting("Sales Representative")
    ops = posting("Operations Manager")
    application_for(sales, email="a@example.com")
    application_for(ops, email="b@example.com", status="shortlisted",
                    phone="+2349011112222")

    def rows(query=""):
        data = client.get(f"{APPS}{query}").data
        return data["results"] if isinstance(data, dict) else data

    assert len(rows(f"?job={sales.pk}")) == 1
    assert len(rows("?status=shortlisted")) == 1
    # Typed the way it is printed on a CV, found against the E.164 stored value.
    assert len(rows("?q=0901 111 2222")) == 1
