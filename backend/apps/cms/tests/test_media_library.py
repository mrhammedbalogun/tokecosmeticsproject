"""The media library (2026-08-07): upload once, attach anywhere.

The attach tests are the point of this file. `image_asset` and friends assign an
EXISTING storage key to the banner's FileField — bypassing the upload path entirely —
so the things that must hold are: the kind gate (an .mp4 can never end up behind an
`<img>`), the two-way sync (a direct upload clears the binding, an unbind clears the
artwork), and the refusal to accept both spellings at once.
"""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.cms.models import Banner, MediaAsset

pytestmark = pytest.mark.django_db

MEDIA = "/api/v1/admin/media/"
BANNERS = "/api/v1/admin/banners/"


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "salmon").save(buf, format="PNG")
    return buf.getvalue()


def upload(client, name="tile.png", content=None, content_type="image/png"):
    return client.post(
        MEDIA, {"file": SimpleUploadedFile(name, content or png_bytes(), content_type)},
        format="multipart",
    )


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


# --- the library itself --------------------------------------------------------------


def test_upload_sniffs_an_image_and_lists_it(client):
    r = upload(client, name="hero shot.png")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["kind"] == "image"
    assert body["original_name"] == "hero shot.png"
    assert body["size"] == len(png_bytes())
    assert body["file"].startswith("http")

    listed = client.get(MEDIA + "?search=hero").json()["results"]
    assert [a["id"] for a in listed] == [body["id"]]
    assert client.get(MEDIA + "?search=nomatch").json()["results"] == []


def test_upload_classifies_video_by_bytes_not_content_type(client):
    # Content-Type says image/png; the bytes are not an image and the name says mp4.
    r = upload(client, name="promo.mp4", content=b"\x00\x00\x00 ftypmp42", content_type="image/png")
    assert r.status_code == 201, r.content
    assert r.json()["kind"] == "video"


def test_upload_refuses_a_file_that_is_neither(client):
    r = upload(client, name="notes.txt", content=b"hello", content_type="text/plain")
    assert r.status_code == 400
    assert "neither" in str(r.json())


def test_upload_enforces_the_size_cap(client, monkeypatch):
    monkeypatch.setattr("apps.cms.admin_serializers.MAX_IMAGE_BYTES", 10)
    r = upload(client)
    assert r.status_code == 400
    assert "under" in str(r.json())


def test_the_library_requires_marketing_manage():
    content_editor = APIClient()
    content_editor.force_authenticate(user=staff_user(email="content@toke.test", role="Content"))
    assert content_editor.get(MEDIA).status_code == 403
    assert APIClient().get(MEDIA).status_code in (401, 403)


# --- attaching to banners ------------------------------------------------------------


def asset(client, **kwargs) -> dict:
    return upload(client, **kwargs).json()


def test_attach_points_the_banner_at_the_assets_file(client):
    a = asset(client)
    banner = Banner.objects.create(title="Glow", placement="category")

    r = client.patch(f"{BANNERS}{banner.id}/", {"image_asset": a["id"]}, format="json")
    assert r.status_code == 200, r.content

    banner.refresh_from_db()
    assert banner.image_asset_id == a["id"]
    assert banner.image.name == MediaAsset.objects.get(id=a["id"]).file.name
    # The wire shape the storefront and the admin both read: a URL to the shared file.
    assert r.json()["image"].endswith(banner.image.name.rsplit("/", 1)[-1])


def test_attach_refuses_a_kind_mismatch(client):
    video = asset(client, name="promo.mp4", content=b"\x00\x00\x00 ftypmp42")
    banner = Banner.objects.create(title="Glow", placement="category")

    r = client.patch(f"{BANNERS}{banner.id}/", {"image_asset": video["id"]}, format="json")
    assert r.status_code == 400
    assert "video" in str(r.json()["image_asset"])

    r = client.patch(f"{BANNERS}{banner.id}/", {"video_asset": asset(client)["id"]}, format="json")
    assert r.status_code == 400


def test_attach_and_upload_together_are_refused(client):
    a = asset(client)
    banner = Banner.objects.create(title="Glow", placement="category")
    r = client.patch(
        f"{BANNERS}{banner.id}/",
        {"image": SimpleUploadedFile("x.png", png_bytes(), "image/png"), "image_asset": a["id"]},
        format="multipart",
    )
    assert r.status_code == 400


def test_a_direct_upload_clears_the_binding(client):
    a = asset(client)
    banner = Banner.objects.create(title="Glow", placement="category")
    client.patch(f"{BANNERS}{banner.id}/", {"image_asset": a["id"]}, format="json")

    r = client.patch(
        f"{BANNERS}{banner.id}/",
        {"image": SimpleUploadedFile("fresh.png", png_bytes(), "image/png")},
        format="multipart",
    )
    assert r.status_code == 200, r.content
    banner.refresh_from_db()
    assert banner.image_asset_id is None
    assert banner.image.name != a["file"]  # a new upload, not the shared key


def test_unbinding_clears_the_artwork_and_clearing_unbinds(client):
    a = asset(client)
    banner = Banner.objects.create(title="Glow", placement="category")
    client.patch(f"{BANNERS}{banner.id}/", {"image_asset": a["id"]}, format="json")

    r = client.patch(f"{BANNERS}{banner.id}/", {"image_asset": None}, format="json")
    assert r.status_code == 200, r.content
    banner.refresh_from_db()
    assert banner.image_asset_id is None and not banner.image

    client.patch(f"{BANNERS}{banner.id}/", {"image_asset": a["id"]}, format="json")
    r = client.patch(f"{BANNERS}{banner.id}/", {"image": None}, format="json")
    assert r.status_code == 200, r.content
    banner.refresh_from_db()
    assert banner.image_asset_id is None and not banner.image


def test_two_banners_can_share_one_asset(client):
    a = asset(client)
    first = Banner.objects.create(title="Tile 1", placement="category")
    second = Banner.objects.create(title="Tile 2", placement="concern")
    for b in (first, second):
        assert client.patch(f"{BANNERS}{b.id}/", {"image_asset": a["id"]}, format="json").status_code == 200
    first.refresh_from_db(); second.refresh_from_db()
    assert first.image.name == second.image.name


# --- the seed command ----------------------------------------------------------------


def test_seed_registers_and_binds_pre_library_artwork(client):
    from django.core.management import call_command

    banner = Banner.objects.create(
        title="Old hero", placement="hero",
        image=SimpleUploadedFile("old.png", png_bytes(), "image/png"),
    )
    twin = Banner.objects.create(title="Old twin", placement="category")
    # Two banners sharing one key, as attach produces — the seed must mint ONE asset.
    twin.image.name = banner.image.name
    twin.save(update_fields=["image"])

    call_command("seed_media_library")
    assert MediaAsset.objects.count() == 1
    a = MediaAsset.objects.get()
    assert a.kind == "image" and a.file.name == banner.image.name
    banner.refresh_from_db(); twin.refresh_from_db()
    assert banner.image_asset_id == a.id and twin.image_asset_id == a.id

    call_command("seed_media_library")  # idempotent
    assert MediaAsset.objects.count() == 1
