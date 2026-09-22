"""The programme admin surface: the intake switch, the applications, and the two
elevations the role matrix cannot see from a URLconf.

`test_admin_role_matrix.py` already proves WHO may reach each endpoint. This file proves
what those endpoints DO — which is the half a permission matrix says nothing about.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.entrepreneurship.factories import application
from apps.entrepreneurship.models import ProgramApplication, ProgramSettings

pytestmark = pytest.mark.django_db

APPS = "/api/v1/admin/entrepreneurship/applications/"
SETTINGS = "/api/v1/admin/entrepreneurship/settings/"


def _client(user):
    """`force_authenticate`, deliberately: WHO may reach these endpoints is proved over
    real HTTP in `apps/accounts/tests/test_admin_role_matrix.py`, and re-proving it here
    would make every test in this file a slower copy of that one. These test what the
    endpoints DO."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def manager(db):
    return staff_user(email="manager@toke.test", role="Manager")


@pytest.fixture
def owner(db):
    return staff_user(email="owner@toke.test", role="Owner")


# ── the intake switch ────────────────────────────────────────────────────────


def test_the_switch_reads_and_writes_without_anyone_having_created_it(manager):
    """A singleton: `load()` materialises the row on first touch, so there is no 404 arm
    and no "open the settings screen once before it works"."""
    client = _client(manager)
    assert ProgramSettings.objects.count() == 0

    assert client.get(SETTINGS).data["is_open"] is True
    response = client.patch(
        SETTINGS, {"is_open": False, "closed_message": "Back in January."},
        format="json",
    )
    assert response.status_code == 200
    assert ProgramSettings.objects.count() == 1
    assert ProgramSettings.load().is_open is False


def test_the_closed_message_is_whitespace_collapsed_because_it_is_published_copy(manager):
    _client(manager).patch(
        SETTINGS, {"closed_message": "  Back   in\n January.  "}, format="json"
    )
    assert ProgramSettings.load().closed_message == "Back in January."


# ── the applications ─────────────────────────────────────────────────────────


def test_the_list_carries_no_motivation_letters(manager):
    """Shipping every student's paragraph in one paginated response is bulk egress of
    exactly the kind `audit_reads` exists to record. The list says WHETHER there is one;
    the detail route serves it, one at a time, which is how a reviewer reads it anyway.
    """
    application(motivation="I already sell to my hostel.")
    row = _client(manager).get(APPS).data["results"][0]

    assert "motivation" not in row
    assert row["has_motivation"] is True


def test_the_detail_route_serves_the_letter_and_the_phone_in_both_forms(manager):
    """The E.164 value is what a `tel:`/WhatsApp link must be BUILT from; the prettified
    national form is only ever the text. Same rule as the store cards."""
    row = application(motivation="I already sell to my hostel.")
    body = _client(manager).get(f"{APPS}{row.pk}/").data

    assert body["motivation"] == "I already sell to my hostel."
    assert body["phone"] == "+2348023900964"
    assert body["phone_display"] and body["phone_display"] != body["phone"]


def test_MOVING_THE_STATUS_STAMPS_THE_REVIEWER_BUT_EDITING_A_NOTE_DOES_NOT(manager):
    """"Reviewed by" answers "who decided". Fixing a typo in the notes is not a
    decision, and a field that says it is makes the audit trail read wrong."""
    client = _client(manager)
    row = application()

    client.patch(f"{APPS}{row.pk}/", {"staff_notes": "typo fix"}, format="json")
    row.refresh_from_db()
    assert row.reviewed_at is None

    client.patch(f"{APPS}{row.pk}/", {"status": "approved"}, format="json")
    row.refresh_from_db()
    assert row.reviewed_at is not None
    assert row.reviewed_by == manager

    # A PATCH carrying the status it already had is a no-op, not a second review.
    first_stamp = row.reviewed_at
    client.patch(f"{APPS}{row.pk}/", {"status": "approved"}, format="json")
    row.refresh_from_db()
    assert row.reviewed_at == first_stamp


def test_A_REVIEWER_CANNOT_REWRITE_THE_STUDENTS_OWN_WORDS(manager):
    """The write serializer is a whitelist of two fields. An admin that can silently
    retype an applicant's name or email is an admin whose records stop being evidence of
    what the applicant actually sent."""
    row = application()
    _client(manager).patch(
        f"{APPS}{row.pk}/",
        {"full_name": "Someone Else", "email": "attacker@evil.test",
         "phone": "+2340000000000", "institution": "Nowhere", "status": "approved"},
        format="json",
    )
    row.refresh_from_db()

    assert row.full_name == "Chidinma Eze"
    assert row.email == "chidinma@example.com"
    assert row.phone == "+2348023900964"
    assert row.institution == "University of Lagos"
    assert row.status == "approved"  # the one field that WAS allowed through


def test_there_is_no_staff_side_create_route(manager):
    """An application is written by a member of the public and by nothing else. A
    staff-side create would produce a row nobody consented to, with an email address
    typed by somebody who is not its owner."""
    assert _client(manager).post(APPS, {}, format="json").status_code == 405


def test_deleting_is_refused_to_a_manager_and_allowed_to_the_owner(manager, owner):
    """The inline elevation the URLconf cannot see. Checked BEFORE the object lookup, so
    an unauthorised caller gets a clean 403 rather than a 404 that tells them whether the
    id exists."""
    row = application()

    denied = _client(manager).delete(f"{APPS}{row.pk}/")
    assert denied.status_code == 403
    assert ProgramApplication.objects.filter(pk=row.pk).exists()

    allowed = _client(owner).delete(f"{APPS}{row.pk}/")
    assert allowed.status_code == 204
    assert not ProgramApplication.objects.filter(pk=row.pk).exists()


def test_the_deletion_audit_row_does_not_itself_copy_the_students_details(owner):
    """A deletion must not be the thing that writes a name and an email into a table
    nobody thought of as holding personal data — the audit log is read by more people
    than this screen is."""
    from apps.core.models import AuditLog

    row = application()
    _client(owner).delete(f"{APPS}{row.pk}/")

    entry = AuditLog.objects.filter(action="destroy").latest("id")
    blob = str(entry.changes)
    assert "chidinma@example.com" not in blob
    assert "Chidinma" not in blob
    # What it DOES record: enough to know which decision was destroyed.
    assert "University of Lagos" in blob


def test_the_search_finds_a_student_by_the_number_as_they_wrote_it(manager):
    """Stored E.164, typed national. Without the suffix match the search silently finds
    nothing, which reads as "that application is gone"."""
    application()
    found = _client(manager).get(f"{APPS}?q=0802 390 0964").data
    assert found["count"] == 1


def test_the_search_finds_a_whole_school_which_is_how_these_are_actually_looked_up(
    manager,
):
    application(email="a@example.com", institution="University of Lagos")
    application(email="b@example.com", institution="Yaba College of Technology")
    found = _client(manager).get(f"{APPS}?q=unilag").data
    assert found["count"] == 0  # the abbreviation is not the stored name
    found = _client(manager).get(f"{APPS}?q=University of Lagos").data
    assert found["count"] == 1


def test_stats_counts_by_status_and_by_country(manager):
    application(email="a@example.com")
    application(email="b@example.com", status="approved")
    body = _client(manager).get(f"{APPS}stats/").data

    assert body["total"] == 2
    assert body["new"] == 1
    assert body["by_status"]["approved"] == 1
    # One row per country, not one per application — the `values().annotate().order_by()`
    # sequence is what makes that true.
    assert len(body["by_country"]) == 1
    assert body["by_country"][0]["count"] == 2
