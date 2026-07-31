"""`ProductImage` as an editable resource — Plan-17a Task 1.

Before 17a an image could be UPLOADED (`POST /admin/products/{slug}/images/`) and never
touched again: `ProductImage` was not routed, so there was no way to delete one, fix its
alt text, or reorder it. The 17a Images tab is impossible without this.

Creation deliberately stays on the existing multipart action rather than moving here.
Two create paths for one model is how the two drift apart, and the upload path already
carries the parser classes and the `product` binding.
"""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.catalog.factories import ProductFactory, ProductVariantFactory
from apps.catalog.models import ProductImage
from apps.catalog.tests.factories_admin import staff_user

# Never touch the real S3 bucket in tests — same storage swap as
# test_admin_image_upload.py, applied through the `settings` fixture because
# `override_settings` is a decorator/context manager and NOT a pytest mark: putting it in
# `pytestmark` raises "got override_settings instead of Mark" at collection time.
IN_MEMORY = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def in_memory_media(settings):
    settings.STORAGES = IN_MEMORY


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(buf, format="PNG")
    return buf.getvalue()


def _image(product, alt="", position=0, variant=None):
    return ProductImage.objects.create(
        product=product,
        image=SimpleUploadedFile("swatch.png", _png_bytes(), content_type="image/png"),
        alt=alt,
        position=position,
        variant=variant,
    )


@pytest.fixture
def admin_client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def test_admin_edits_alt_text(admin_client):
    img = _image(ProductFactory(), alt="")

    r = admin_client.patch(f"/api/v1/admin/images/{img.id}/", {"alt": "green swatch"})

    assert r.status_code == 200, r.data
    img.refresh_from_db()
    assert img.alt == "green swatch"


def test_admin_reorders_by_writing_position(admin_client):
    p = ProductFactory()
    first, second = _image(p, position=0), _image(p, position=1)

    assert admin_client.patch(f"/api/v1/admin/images/{first.id}/", {"position": 1}).status_code == 200
    assert admin_client.patch(f"/api/v1/admin/images/{second.id}/", {"position": 0}).status_code == 200

    # Model Meta orders on ["position", "id"], so the list order IS the gallery order.
    assert list(p.images.values_list("id", flat=True)) == [second.id, first.id]


def test_admin_attaches_an_image_to_a_variant(admin_client):
    p = ProductFactory()
    v = ProductVariantFactory(product=p)
    img = _image(p)

    r = admin_client.patch(f"/api/v1/admin/images/{img.id}/", {"variant": v.id})

    assert r.status_code == 200, r.data
    img.refresh_from_db()
    assert img.variant_id == v.id


def test_admin_deletes_an_image(admin_client):
    img = _image(ProductFactory())

    r = admin_client.delete(f"/api/v1/admin/images/{img.id}/")

    assert r.status_code == 204, getattr(r, "data", r)
    assert not ProductImage.objects.filter(id=img.id).exists()


def test_patch_cannot_move_an_image_to_another_product(admin_client):
    """`product` is `read_only` on the serializer. Without that, a PATCH could reparent
    somebody else's photograph onto a different product and the gallery would silently
    change under a page nobody had opened."""
    owner, thief = ProductFactory(slug="owner"), ProductFactory(slug="thief")
    img = _image(owner)

    r = admin_client.patch(f"/api/v1/admin/images/{img.id}/", {"product": thief.id})

    assert r.status_code == 200, r.data
    img.refresh_from_db()
    assert img.product_id == owner.id


def test_the_resource_refuses_to_create(admin_client):
    """Uploading stays on `POST /admin/products/{slug}/images/`, which owns the multipart
    parsing and binds `product` from the URL. A second create path would drift from it."""
    p = ProductFactory()

    r = admin_client.post("/api/v1/admin/images/", {"product": p.id, "alt": "x"})

    assert r.status_code == 405, getattr(r, "data", r)


def test_the_resource_refuses_a_whole_body_put(admin_client):
    """PUT means "replace the record", and the record's `image` file cannot be replaced
    through this JSON route — a PUT that silently ignored it would be a lie."""
    img = _image(ProductFactory(), alt="keep me")

    r = admin_client.put(f"/api/v1/admin/images/{img.id}/", {"alt": "clobbered"})

    assert r.status_code == 405, getattr(r, "data", r)
    img.refresh_from_db()
    assert img.alt == "keep me"


def test_images_filter_by_product(admin_client):
    wanted, other = ProductFactory(slug="wanted"), ProductFactory(slug="other")
    _image(wanted, alt="mine-1")
    _image(wanted, alt="mine-2", position=1)
    _image(other, alt="theirs")

    r = admin_client.get(f"/api/v1/admin/images/?product={wanted.id}")

    assert r.status_code == 200, r.data
    assert {row["alt"] for row in r.data["results"]} == {"mine-1", "mine-2"}


def test_anonymous_is_refused():
    img = _image(ProductFactory())

    r = APIClient().patch(f"/api/v1/admin/images/{img.id}/", {"alt": "nope"})

    assert r.status_code in (401, 403)
    img.refresh_from_db()
    assert img.alt == ""
