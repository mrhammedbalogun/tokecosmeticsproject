import pytest
from django.core.management import call_command

from apps.catalog.models import Product, ProductImage

pytestmark = pytest.mark.django_db


def test_thumbnail_becomes_position_zero_image(artifact_path, uploads_root):
    call_command("import_catalog", str(artifact_path), "--uploads-root", str(uploads_root))
    first = Product.objects.get(slug="toke-scented-shea-butter").images.order_by("position").first()
    assert first.position == 0
    assert "toke-shea" in first.image.name


def test_gallery_and_acf_images_follow_the_thumbnail(artifact_path, uploads_root):
    call_command("import_catalog", str(artifact_path), "--uploads-root", str(uploads_root))
    assert Product.objects.get(slug="toke-scented-shea-butter").images.count() == 3


def test_missing_file_is_skipped_not_fatal(artifact_path, uploads_root, capsys):
    """Product 105's attachment is deliberately absent from the fixture tree."""
    call_command("import_catalog", str(artifact_path), "--uploads-root", str(uploads_root))
    assert Product.objects.filter(slug="toke-hair-food").exists()
    assert Product.objects.get(slug="toke-hair-food").images.count() == 0
    assert "missing" in capsys.readouterr().out.lower()


def test_product_with_no_image_reference_is_fine(artifact_path, uploads_root):
    """Distinct from a broken reference: 107 never had an image configured."""
    call_command("import_catalog", str(artifact_path), "--uploads-root", str(uploads_root))
    assert Product.objects.get(slug="toke-lip-balm").images.count() == 0


def test_images_do_not_duplicate_on_rerun(artifact_path, uploads_root):
    for _ in range(2):
        call_command("import_catalog", str(artifact_path), "--uploads-root", str(uploads_root))
    assert Product.objects.get(slug="toke-scented-shea-butter").images.count() == 3


def test_skip_media_creates_no_images(artifact_path, uploads_root):
    call_command("import_catalog", str(artifact_path), "--uploads-root", str(uploads_root), "--skip-media")
    assert ProductImage.objects.count() == 0


def test_dry_run_uploads_nothing_to_storage(artifact_path, uploads_root, settings, tmp_path):
    """THE DRY-RUN CONTRACT. The DB rolls back, but a file written to storage
    would NOT be undone — that would silently break the review gate."""
    media_root = tmp_path / "media_under_test"
    media_root.mkdir()
    settings.MEDIA_ROOT = str(media_root)

    call_command("import_catalog", str(artifact_path), "--uploads-root", str(uploads_root), "--dry-run")

    assert ProductImage.objects.count() == 0
    written = [p for p in media_root.rglob("*") if p.is_file()]
    assert written == [], f"dry run wrote files to storage: {written}"
