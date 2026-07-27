"""Tests for the one-shot `prune_truncated_orphan_images` command.

This command exists to clean up ONE specific defect and is deleted once the
production run is verified. These tests are the permanent record of what it was
ever allowed to touch.

The defect: ImageField's default max_length=100 silently truncates (storage
never raises), so 39 of 207 image paths were stored truncated. Widening the
field to IMAGE_PATH_MAX and re-importing created correct rows and left the
truncated ones behind as orphans.

The danger: `importers/media.py` deliberately REFUSES to delete orphans,
because "key is not in the source" cannot distinguish a stale row from an image
a staff member uploaded by hand. So "not in source" alone must never be enough
to delete. This command requires the truncation signature as well — two
predicates, both mandatory.
"""
from pathlib import Path

import pytest
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalog.models import Product, ProductImage

pytestmark = pytest.mark.django_db

PREFIX = "catalog/products/"
TRUNCATED_LEN = 100  # the truncation fingerprint


def _import(artifact_path, uploads_root, deletes):
    """Import, then forget any storage deletes it made.

    `import_media` legitimately deletes when overwriting a target path
    (media.py). Only deletes made by the PRUNE command are of interest, so the
    spy is cleared once the fixture data is in place.
    """
    call_command("import_catalog", str(artifact_path), "--uploads-root", str(uploads_root))
    deletes.clear()


def _canonical_key(product):
    """A real canonical key: the basename of an image the importer just wrote."""
    return Path(product.images.first().image.name).name


def _name_of_exact_length(key, length=TRUNCATED_LEN):
    """Build a stored name of exactly `length` chars whose basename is `key`."""
    pad = length - len(PREFIX) - 1 - len(key)
    assert pad > 0, "key too long to pad to the target length"
    return f"{PREFIX}{'x' * pad}/{key}"


def _add_image(product, name, position=99):
    """Create a ProductImage with an exact stored name, bypassing storage.

    No bytes are written: selection reads `image.name` only, and the command
    must never touch storage.
    """
    image = ProductImage(product=product, alt=product.name, position=position)
    image.image.name = name
    image.save()
    return image


@pytest.fixture
def deletes(monkeypatch):
    """Records every storage delete, so a test can prove the command made none.

    S3 bucket versioning is OFF, so a storage delete is unrecoverable. This
    command deletes ROWS only; the S3 objects are swept later, in Plan-25/26,
    once versioning is on.
    """
    recorded: list[str] = []
    original = FileSystemStorage.delete

    def _spy(self, name):
        recorded.append(name)
        return original(self, name)

    monkeypatch.setattr(FileSystemStorage, "delete", _spy)
    return recorded


def test_apply_deletes_a_truncated_orphan(artifact_path, uploads_root, deletes):
    _import(artifact_path, uploads_root, deletes)
    product = Product.objects.get(slug="toke-scented-shea-butter")
    orphan = _add_image(product, _name_of_exact_length("9999-stale-truncated-file.jpg"))

    call_command("prune_truncated_orphan_images", str(artifact_path), "--apply", "--expect", "1")

    assert not ProductImage.objects.filter(pk=orphan.pk).exists()
    assert deletes == [], "rows only — the storage object is swept later"


def test_dry_run_is_the_default_and_deletes_nothing(
    artifact_path, uploads_root, deletes
):
    _import(artifact_path, uploads_root, deletes)
    product = Product.objects.get(slug="toke-scented-shea-butter")
    orphan = _add_image(product, _name_of_exact_length("9999-stale-truncated-file.jpg"))

    call_command("prune_truncated_orphan_images", str(artifact_path))

    assert ProductImage.objects.filter(pk=orphan.pk).exists()


def test_legitimate_hundred_char_image_is_never_selected(
    artifact_path, uploads_root, deletes
):
    """The row that made LENGTH(image)=100 unsafe as a sole selector.

    One live image's real path is exactly 100 chars. It is current, not
    truncated. Its key IS in the source, so predicate 1 protects it.
    """
    _import(artifact_path, uploads_root, deletes)
    product = Product.objects.get(slug="toke-scented-shea-butter")
    legit = product.images.first()
    legit.image.name = _name_of_exact_length(_canonical_key(product))
    legit.save()
    assert len(legit.image.name) == TRUNCATED_LEN

    call_command("prune_truncated_orphan_images", str(artifact_path), "--apply", "--expect", "0")

    assert ProductImage.objects.filter(pk=legit.pk).exists()


def test_full_length_orphan_is_never_selected(artifact_path, uploads_root, deletes):
    """A hand-uploaded staff image, or one whose source file vanished between
    runs, is absent from the source but NOT truncated. Predicate 2 protects it.
    """
    _import(artifact_path, uploads_root, deletes)
    product = Product.objects.get(slug="toke-scented-shea-butter")
    hand_upload = _add_image(product, f"{PREFIX}{product.slug}/staff-uploaded-by-hand.jpg")
    assert len(hand_upload.image.name) != TRUNCATED_LEN

    call_command("prune_truncated_orphan_images", str(artifact_path), "--apply", "--expect", "0")

    assert ProductImage.objects.filter(pk=hand_upload.pk).exists()


def test_aborts_without_deleting_when_count_differs_from_expected(
    artifact_path, uploads_root, deletes
):
    """The production run expects exactly 38. Any other number means the world
    changed since the analysis and a human must look before anything is deleted.
    """
    _import(artifact_path, uploads_root, deletes)
    product = Product.objects.get(slug="toke-scented-shea-butter")
    orphan = _add_image(product, _name_of_exact_length("9999-stale-truncated-file.jpg"))

    with pytest.raises(CommandError, match="expected 38"):
        call_command(
            "prune_truncated_orphan_images", str(artifact_path), "--apply", "--expect", "38"
        )

    assert ProductImage.objects.filter(pk=orphan.pk).exists()


def test_manifest_records_the_storage_keys_left_behind(
    artifact_path, uploads_root, tmp_path, deletes
):
    """The S3 objects outlive the rows, so their keys must be written down or
    they become unfindable garbage.
    """
    _import(artifact_path, uploads_root, deletes)
    product = Product.objects.get(slug="toke-scented-shea-butter")
    name = _name_of_exact_length("9999-stale-truncated-file.jpg")
    _add_image(product, name)
    manifest = tmp_path / "orphaned-s3-objects.txt"

    call_command(
        "prune_truncated_orphan_images",
        str(artifact_path),
        "--apply",
        "--expect", "1",
        "--manifest", str(manifest),
    )

    assert name in manifest.read_text(encoding="utf-8")
