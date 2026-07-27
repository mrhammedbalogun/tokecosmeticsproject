import json

import pytest
from django.core.management import call_command

from apps.catalog.models import Product, ProductImage
from apps.migration_wp.importers.media import import_media

pytestmark = pytest.mark.django_db

_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


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


def test_thumbnail_wins_position_zero_even_when_its_id_is_higher(artifact_path, uploads_root):
    """4 live products have an ACF image with a lower attachment id than their
    thumbnail. Ordering by id would put the wrong image first — customers would
    see the wrong main product image."""
    call_command("import_catalog", str(artifact_path), "--uploads-root", str(uploads_root))
    images = list(
        Product.objects.get(slug="toke-scented-shea-butter").images.order_by("position")
    )
    assert "toke-shea.jpg" in images[0].image.name
    assert "toke-shea-acf-early" in images[-1].image.name


def test_rerun_after_removing_a_source_image_repositions_and_flags_orphan(
    artifact_path, uploads_root, capsys
):
    """Reproduces: product 101 starts with images at positions 0/1/2 (thumbnail,
    gallery, ACF-early). WordPress then drops the gallery reference. Re-running
    must NOT leave the now-orphaned gallery image sitting ahead of the image
    that should now be second -- the storefront would show a stale, wrong
    image in that slot. The orphan is never deleted (no provenance marker to
    tell it apart from a staff upload), just pushed after and counted."""
    call_command("import_catalog", str(artifact_path), "--uploads-root", str(uploads_root))

    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    del data["meta"]["101"]["_product_image_gallery"]
    artifact_path.write_text(json.dumps(data), encoding="utf-8")

    call_command("import_catalog", str(artifact_path), "--uploads-root", str(uploads_root))

    images = list(
        Product.objects.get(slug="toke-scented-shea-butter").images.order_by("position")
    )
    assert [img.position for img in images] == [0, 1, 2]
    assert "toke-shea.jpg" in images[0].image.name  # thumbnail: still position 0
    assert "toke-shea-acf-early" in images[1].image.name  # contiguous next source image
    assert "toke-shea-2" in images[2].image.name  # orphaned gallery image, pushed last

    assert "1 orphan_images" in capsys.readouterr().out


def test_dry_run_and_real_run_report_the_same_copied_count(artifact_path, uploads_root):
    """The dry run is the store owner's review gate -- its counts must match
    what a real run would actually do, or the review is misleading."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    data = json.loads(artifact_path.read_text(encoding="utf-8"))

    dry_copied, dry_missing, dry_orphans, _ = import_media(data, str(uploads_root), True)
    real_copied, real_missing, real_orphans, _ = import_media(data, str(uploads_root), False)

    assert dry_copied == real_copied
    assert dry_missing == real_missing
    assert dry_orphans == real_orphans == 0


def test_two_attachments_sharing_a_basename_in_different_folders_both_import(
    artifact_path, uploads_root
):
    """WordPress routinely has files with the same name in different upload-month
    folders (e.g. two different IMG_1234.jpg uploads). Deduping on the bare
    filename would silently drop the second one; deduping on
    <attachment_id>-<filename> keeps both."""
    call_command("import_catalog", str(artifact_path), "--skip-media")

    (uploads_root / "2024" / "01").mkdir(parents=True, exist_ok=True)
    (uploads_root / "2025" / "11").mkdir(parents=True, exist_ok=True)
    (uploads_root / "2024" / "01" / "banner.jpg").write_bytes(_PNG_BYTES)
    (uploads_root / "2025" / "11" / "banner.jpg").write_bytes(_PNG_BYTES)

    data = {
        "products": [{"ID": 101}],
        "meta": {"101": {"_thumbnail_id": "9101", "_product_image_gallery": "9102"}},
        "attachments": {"9101": "2024/01/banner.jpg", "9102": "2025/11/banner.jpg"},
    }

    copied, missing, orphan_images, _ = import_media(data, str(uploads_root), False)

    assert copied == 2
    assert missing == 0
    names = {
        img.image.name
        for img in Product.objects.get(slug="toke-scented-shea-butter").images.all()
    }
    assert any("9101-banner.jpg" in n for n in names)
    assert any("9102-banner.jpg" in n for n in names)


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
