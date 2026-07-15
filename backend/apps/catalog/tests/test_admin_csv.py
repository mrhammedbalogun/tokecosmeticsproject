from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.catalog.csv_io import import_products_csv
from apps.catalog.models import Product
from apps.catalog.tests.factories_admin import staff_user
from apps.pricing.models import Price


@pytest.mark.django_db
def test_import_products_csv_service_creates_and_reports_errors():
    rows = [
        # good row
        {"slug": "serum", "name": "Serum", "brand_slug": "", "status": "active",
         "short_description": "", "category_slugs": "", "sku": "SER-1",
         "variant_name": "50ml", "price_ngn": "5000", "price_gbp": "9.99",
         "price_usd": "", "price_cad": ""},
        # bad row: missing sku
        {"slug": "bad", "name": "Bad", "brand_slug": "", "status": "active",
         "short_description": "", "category_slugs": "", "sku": "",
         "variant_name": "x", "price_ngn": "1", "price_gbp": "",
         "price_usd": "", "price_cad": ""},
    ]
    report = import_products_csv(rows)
    assert report["created"] == 1
    assert len(report["errors"]) == 1
    assert report["errors"][0]["row"] == 2

    p = Product.objects.get(slug="serum")
    v = p.variants.get(sku="SER-1")
    assert Price.objects.filter(variant=v, currency__code="NGN", amount=Decimal("5000")).exists()
    assert Price.objects.filter(variant=v, currency__code="GBP", amount=Decimal("9.99")).exists()


@pytest.mark.django_db
def test_export_then_reimport_roundtrip(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    c = APIClient()
    c.force_authenticate(user=staff_user())

    csv_text = (
        "slug,name,brand_slug,status,short_description,category_slugs,sku,variant_name,price_ngn,price_gbp,price_usd,price_cad\n"
        "glow,Glow,,active,,,GLOW-1,50ml,7000,,,\n"
    )
    upload = SimpleUploadedFile("import.csv", csv_text.encode(), content_type="text/csv")
    r = c.post("/api/v1/admin/products/import.csv", {"file": upload}, format="multipart")
    assert r.status_code == 200, r.data
    assert r.data["created"] == 1
    assert Product.objects.filter(slug="glow").exists()

    r = c.get("/api/v1/admin/products/export.csv")
    assert r.status_code == 200
    body = b"".join(r.streaming_content).decode() if hasattr(r, "streaming_content") else r.content.decode()
    assert "glow" in body
    assert "GLOW-1" in body


@pytest.mark.django_db
def test_csv_endpoints_require_staff():
    assert APIClient().get("/api/v1/admin/products/export.csv").status_code in (401, 403)
