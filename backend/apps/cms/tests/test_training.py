"""The staff training library (2026-08-23).

Role gating over real HTTP lives in `test_admin_role_matrix.py` (the two Rows added
with this feature); the surface wiring in `test_admin_surface_guard.py`. This file
tests what those cannot: the link parser, the canonicalisation, the duplicate
refusal, and the one behavioural rule that matters — a draft is invisible to staff.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.cms.models import TrainingResource
from apps.cms.youtube import canonical_watch_url, parse_youtube_video_id

pytestmark = pytest.mark.django_db

VID = "dQw4w9WgXcQ"
VID2 = "abc123XYZ_-"


@pytest.fixture
def owner():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


@pytest.fixture
def support():
    c = APIClient()
    c.force_authenticate(user=staff_user(email="support@toke.test", role="Support"))
    return c


# --- the parser (no db) --------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VID}",
        f"https://youtube.com/watch?v={VID}",
        f"https://m.youtube.com/watch?v={VID}&list=PLx&index=2",
        f"https://www.youtube.com/watch?t=42&v={VID}",  # params in any order
        f"https://youtu.be/{VID}",
        f"https://youtu.be/{VID}?si=SHARETRACKING&t=90",
        f"youtu.be/{VID}",  # pasted without a scheme
        f"www.youtube.com/watch?v={VID}",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/embed/{VID}",
        f"https://www.youtube.com/live/{VID}",
        f"https://www.youtube-nocookie.com/embed/{VID}",
    ],
)
def test_every_real_link_shape_parses(url):
    assert parse_youtube_video_id(url) == VID


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "https://vimeo.com/12345678",  # right idea, wrong platform
        "https://notyoutube.com/watch?v=" + VID,  # host allowlist, not "contains"
        "https://youtube.com.evil.example/watch?v=" + VID,
        "https://www.youtube.com/",  # no video named
        "https://www.youtube.com/@TokeCosmetics",  # a channel is not a video
        "https://www.youtube.com/playlist?list=PLx",  # a playlist without v=
        "https://www.youtube.com/watch?v=tooshort",  # not an 11-char id
        "ftp://youtu.be/" + VID,  # scheme allowlist
        "javascript:alert(1)",  # must never survive to an iframe src
    ],
)
def test_a_link_that_names_no_video_is_refused(url):
    assert parse_youtube_video_id(url) is None


# --- authoring -----------------------------------------------------------------------


def test_create_canonicalises_the_pasted_link(owner):
    r = owner.post(
        "/api/v1/admin/training/",
        {"title": "Packing an order", "description": "Watch before your first shift.",
         "youtube_url": f"https://youtu.be/{VID}?si=xyz&t=30"},
        format="json",
    )
    assert r.status_code == 201, r.content
    assert r.data["video_id"] == VID
    assert r.data["youtube_url"] == canonical_watch_url(VID)
    assert r.data["is_published"] is True  # live by default; drafting is opt-out


def test_a_bad_link_is_refused_under_its_field(owner):
    r = owner.post(
        "/api/v1/admin/training/",
        {"title": "x", "youtube_url": "https://vimeo.com/123"},
        format="json",
    )
    assert r.status_code == 400
    assert "youtube_url" in r.data
    assert TrainingResource.objects.count() == 0


def test_a_blank_title_is_refused(owner):
    r = owner.post(
        "/api/v1/admin/training/",
        {"title": "   ", "youtube_url": f"https://youtu.be/{VID}"},
        format="json",
    )
    assert r.status_code == 400
    assert "title" in r.data


def test_the_same_video_cannot_be_added_twice(owner):
    TrainingResource.objects.create(title="First", youtube_url=canonical_watch_url(VID))
    r = owner.post(
        "/api/v1/admin/training/",
        # A DIFFERENT spelling of the SAME video — the check is on the id, not the text.
        {"title": "Second", "youtube_url": f"https://youtu.be/{VID}"},
        format="json",
    )
    assert r.status_code == 400
    assert "First" in str(r.data["youtube_url"])
    assert TrainingResource.objects.count() == 1


def test_editing_the_link_re_derives_the_id(owner):
    row = TrainingResource.objects.create(title="T", youtube_url=canonical_watch_url(VID))
    r = owner.patch(
        f"/api/v1/admin/training/{row.pk}/",
        {"youtube_url": f"https://youtu.be/{VID2}"},
        format="json",
    )
    assert r.status_code == 200, r.content
    row.refresh_from_db()
    assert row.video_id == VID2
    assert row.youtube_url == canonical_watch_url(VID2)


def test_a_publish_flip_needs_no_link(owner):
    """PATCHing `is_published` alone must not demand the URL again — the hide/show
    button sends exactly one field."""
    row = TrainingResource.objects.create(title="T", youtube_url=canonical_watch_url(VID))
    r = owner.patch(
        f"/api/v1/admin/training/{row.pk}/", {"is_published": False}, format="json"
    )
    assert r.status_code == 200, r.content
    row.refresh_from_db()
    assert row.is_published is False
    assert row.video_id == VID  # untouched


def test_delete_really_deletes(owner):
    row = TrainingResource.objects.create(title="T", youtube_url=canonical_watch_url(VID))
    assert owner.delete(f"/api/v1/admin/training/{row.pk}/").status_code == 204
    assert TrainingResource.objects.count() == 0


def test_support_cannot_author(support):
    """The matrix pins GET per role; this pins a WRITE, which its rows never fire."""
    r = support.post(
        "/api/v1/admin/training/",
        {"title": "x", "youtube_url": f"https://youtu.be/{VID}"},
        format="json",
    )
    assert r.status_code == 403


# --- the library staff see -----------------------------------------------------------


def test_the_library_is_published_rows_in_curriculum_order(support):
    TrainingResource.objects.create(
        title="Second", youtube_url=canonical_watch_url(VID2), position=2
    )
    TrainingResource.objects.create(
        title="First", youtube_url=canonical_watch_url(VID), position=1
    )
    r = support.get("/api/v1/admin/training-library/")
    assert r.status_code == 200
    assert [row["title"] for row in r.data] == ["First", "Second"]


def test_a_draft_is_invisible_to_staff(owner, support):
    TrainingResource.objects.create(
        title="Draft", youtube_url=canonical_watch_url(VID), is_published=False
    )
    assert support.get("/api/v1/admin/training-library/").data == []
    # ... and visible to the Owner's management list, which is where drafts live.
    titles = [row["title"] for row in owner.get("/api/v1/admin/training/").data]
    assert titles == ["Draft"]
