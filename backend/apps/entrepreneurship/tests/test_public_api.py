"""The anonymous programme surface: the config read, and applying.

The tests that matter here are not the happy path. They are the four edge cases the
design turns on — the response is identical whatever happened, a resubmission replaces
rather than duplicates, a DECIDED application cannot be overwritten by anybody who knows
an address, and a closed intake is enforced at the write rather than at the page.
"""
import pytest
from rest_framework.test import APIClient

from apps.core.models import Country
from apps.entrepreneurship.factories import VALID_PAYLOAD, application
from apps.entrepreneurship.models import ProgramApplication, ProgramSettings

pytestmark = pytest.mark.django_db

APPLY = "/api/v1/entrepreneurship/apply/"
CONFIG = "/api/v1/entrepreneurship/config/"


@pytest.fixture
def client():
    return APIClient()


# ── the config read ──────────────────────────────────────────────────────────


def test_config_reports_open_on_a_database_that_has_never_seen_the_switch(client):
    """A fresh install must not look closed. `ProgramSettings.load()` materialises the
    row with `is_open=True`, which is the state the programme is in for all but a few
    weeks of its life."""
    assert not ProgramSettings.objects.exists()
    response = client.get(CONFIG)
    assert response.status_code == 200
    assert response.data["is_open"] is True


def test_config_offers_the_real_markets_and_never_the_pricing_bucket(client):
    """"ZZ / International" is a currency fallback, not a place anybody studies in.
    Offering it would put a choice in the dropdown that the apply endpoint refuses."""
    codes = {row["code"] for row in client.get(CONFIG).data["countries"]}
    assert "NG" in codes
    assert "ZZ" not in codes


def test_config_carries_the_closed_sentence_even_while_open(client):
    """So a client that cached this response and later sees `is_open` flip still has the
    words to render. The default is a real sentence, not an empty string — an operator
    who switches the intake off without typing anything still gets something that reads
    as a decision rather than a blank space."""
    body = client.get(CONFIG).data
    assert body["is_open"] is True
    assert len(body["closed_message"]) > 20


# ── applying ─────────────────────────────────────────────────────────────────


def test_a_first_application_is_stored_and_normalised(client):
    response = client.post(APPLY, {**VALID_PAYLOAD, "email": "  Chidinma@Example.COM "},
                           format="json")
    assert response.status_code == 201, response.data

    row = ProgramApplication.objects.get()
    # Lowercased in `save()`. Without it the partial unique index cannot see a collision
    # and one person appears twice under two spellings of one address.
    assert row.email == "chidinma@example.com"
    assert row.status == "new"
    assert row.submission_count == 1
    assert row.is_resubmission is False


def test_THE_RESPONSE_IS_IDENTICAL_WHETHER_OR_NOT_THEY_HAVE_APPLIED_BEFORE(client):
    """The privacy property the whole de-duplication design exists to preserve.

    Answering "you have already applied" would prove to whoever typed an address that
    its owner is looking for a way to make money — the same third-party fact
    `accounts.views.PasswordResetView` refuses to confirm. The status code AND the body
    must match, or the response itself becomes the oracle.
    """
    first = client.post(APPLY, VALID_PAYLOAD, format="json")
    second = client.post(APPLY, VALID_PAYLOAD, format="json")

    assert first.status_code == second.status_code == 201
    assert first.data == second.data


def test_a_resubmission_while_undecided_replaces_rather_than_duplicates(client):
    """Also the student's own fix for the course they typed wrong — without emailing
    anybody, which is the single most common support message a form like this makes."""
    client.post(APPLY, VALID_PAYLOAD, format="json")
    client.post(APPLY, {**VALID_PAYLOAD, "course_of_study": "Microbiology"},
                format="json")

    row = ProgramApplication.objects.get()
    assert row.course_of_study == "Microbiology"
    assert row.submission_count == 2


def test_A_DECIDED_APPLICATION_CANNOT_BE_OVERWRITTEN_BY_ANYONE_WHO_KNOWS_THE_ADDRESS(
    client,
):
    """The other half of the rule, and the one that protects the reviewer.

    Once staff have moved the status, the row is the record of a decision. A second
    submission makes a SECOND row, flagged, so nobody can destroy a review in progress
    by knowing an email address — and the reviewer can see both.
    """
    decided = application(status="in_review", staff_notes="Called her, promising.")

    response = client.post(APPLY, VALID_PAYLOAD, format="json")
    assert response.status_code == 201

    decided.refresh_from_db()
    assert decided.status == "in_review"
    assert decided.staff_notes == "Called her, promising."

    fresh = ProgramApplication.objects.exclude(pk=decided.pk).get()
    assert fresh.is_resubmission is True


def test_a_rejected_student_can_apply_again_next_session(client):
    """The partial unique index stops applying the moment a row is decided, which is
    what makes re-applying in a later academic year work at all."""
    application(status="rejected")
    assert client.post(APPLY, VALID_PAYLOAD, format="json").status_code == 201
    assert ProgramApplication.objects.count() == 2


def test_a_closed_intake_is_refused_at_the_write_and_says_why(client):
    """The storefront's copy of `is_open` is a cached read and is stale by construction.
    THIS is the authority, and it re-reads the row under a lock inside the same
    transaction that would write the application."""
    settings_row = ProgramSettings.load()
    settings_row.is_open = False
    settings_row.closed_message = "Applications reopen in January."
    settings_row.save()

    response = client.post(APPLY, VALID_PAYLOAD, format="json")

    assert response.status_code == 409
    assert response.data["detail"] == "Applications reopen in January."
    assert not ProgramApplication.objects.exists()


def test_the_honeypot_answers_201_and_stores_nothing(client):
    """A bot told it failed retries differently; a bot told it succeeded stops."""
    response = client.post(APPLY, {**VALID_PAYLOAD, "website": "http://spam.test"},
                           format="json")
    assert response.status_code == 201
    assert not ProgramApplication.objects.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("phone", "0802 390 0964"),      # national form, no country code
        ("phone", "not a phone"),
        ("email", "chidinma@"),
        ("full_name", " "),
        ("institution", ""),
        ("course_of_study", ""),
        ("country", "ZZ"),               # the pricing bucket
        ("country", "XX"),               # not a market at all
    ],
)
def test_a_bad_field_is_refused_by_name_so_the_form_can_paint_it(client, field, value):
    response = client.post(APPLY, {**VALID_PAYLOAD, field: value}, format="json")
    assert response.status_code == 400
    assert field in response.data, response.data
    assert not ProgramApplication.objects.exists()


def test_the_phone_is_stored_e164_so_a_tel_link_dials(client):
    client.post(APPLY, {**VALID_PAYLOAD, "phone": "+234 802 390 0964"}, format="json")
    assert ProgramApplication.objects.get().phone == "+2348023900964"


def test_the_optional_fields_are_genuinely_optional(client):
    """A social handle and a reason are the two fields most likely to be skipped on a
    phone. Requiring either would cost real applications for a reviewer's convenience."""
    payload = {k: v for k, v in VALID_PAYLOAD.items()}
    response = client.post(APPLY, payload, format="json")
    assert response.status_code == 201
    row = ProgramApplication.objects.get()
    assert row.social_handle == ""
    assert row.motivation == ""


def test_a_social_handle_is_accepted_in_whatever_shape_it_was_typed(client):
    """Every rule that would refuse one of these refuses a real answer on an OPTIONAL
    field — the worst trade on a form."""
    for handle in ["@ada.sells", "instagram.com/ada.sells", "Ada on TikTok"]:
        ProgramApplication.objects.all().delete()
        response = client.post(
            APPLY, {**VALID_PAYLOAD, "social_handle": handle}, format="json"
        )
        assert response.status_code == 201, (handle, response.data)
        assert ProgramApplication.objects.get().social_handle == handle


def test_the_applicant_is_never_told_which_country_rows_exist(client):
    """The country error names what to do, not what our database holds. DRF's default
    ("Object with code=XX does not exist") is a sentence about our schema written at a
    student."""
    response = client.post(APPLY, {**VALID_PAYLOAD, "country": "XX"}, format="json")
    assert "does not exist" not in str(response.data["country"][0]).lower()


def test_a_second_market_is_accepted(client):
    """The programme runs in four markets — the WordPress form's country list was
    Nigeria, the UK, the US and Canada, and this is the one that proves the FK is not
    quietly pinned to NG."""
    Country.objects.get(code="GB")
    response = client.post(
        APPLY, {**VALID_PAYLOAD, "country": "GB", "academic_level": "Year 2"},
        format="json",
    )
    assert response.status_code == 201
    assert ProgramApplication.objects.get().country_id == "GB"
