import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.catalog.factories import ProductFactory
from apps.catalog.tests.factories_admin import staff_user


def _png_bytes():
    """A real 1x1 PNG so Pillow's ImageField validation accepts it."""
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(buf, format="PNG")
    return buf.getvalue()


# Never touch the real S3 bucket in tests — use in-memory media storage.
IN_MEMORY = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=IN_MEMORY)
@pytest.mark.django_db
def test_admin_uploads_product_image():
    p = ProductFactory()
    c = APIClient()
    c.force_authenticate(user=staff_user())

    upload = SimpleUploadedFile("swatch.png", _png_bytes(), content_type="image/png")
    r = c.post(
        f"/api/v1/admin/products/{p.slug}/images/",
        {"image": upload, "alt": "swatch"},
        format="multipart",
    )
    assert r.status_code == 201, r.data
    assert p.images.count() == 1
    assert p.images.first().alt == "swatch"


@override_settings(STORAGES=IN_MEMORY)
@pytest.mark.django_db
def test_image_upload_requires_staff():
    p = ProductFactory()
    upload = SimpleUploadedFile("swatch.png", _png_bytes(), content_type="image/png")
    r = APIClient().post(
        f"/api/v1/admin/products/{p.slug}/images/", {"image": upload}, format="multipart"
    )
    assert r.status_code in (401, 403)
