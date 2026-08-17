"""Thumbnail generation, and which picture represents a variant.

The pipeline exists because catalogue photography averages 549KB (max 1.9MB) in
production, and email clients fetch whatever `src` says with nothing resizing it in
between — see `apps/catalog/thumbnails.py`.
"""
from io import BytesIO

import pytest
from PIL import Image

from apps.catalog.factories import ProductVariantFactory
from apps.catalog.images import storage_url, variant_image_alt, variant_image_path
from apps.catalog.models import ProductImage
from apps.catalog.thumbnails import THUMBNAIL_SIZE, thumbnail_name

pytestmark = pytest.mark.django_db


def upload(width=2000, height=1200, fmt="JPEG", name="shot.jpg"):
    from django.core.files.base import ContentFile

    buffer = BytesIO()
    Image.new("RGB", (width, height), (200, 120, 90)).save(buffer, format=fmt, quality=95)
    return ContentFile(buffer.getvalue(), name=name), len(buffer.getvalue())


def make_image(product, **kwargs):
    content, size = upload(**kwargs)
    image = ProductImage(product=product, **{})
    image.image.save(content.name, content, save=False)
    image.product = product
    image.save()
    return image, size


# ── generation ──────────────────────────────────────────────────────────────────────

def test_a_thumbnail_is_generated_on_save():
    variant = ProductVariantFactory()
    image, _ = make_image(variant.product)
    assert image.thumbnail


def test_the_thumbnail_is_square_even_from_a_wide_source():
    """Outlook's Word engine ignores `object-fit`, so a non-square photo forced into a
    64x64 box is DISTORTED. Cropping server-side is the only fix that reaches it."""
    variant = ProductVariantFactory()
    image, _ = make_image(variant.product, width=2000, height=1200)

    with Image.open(image.thumbnail) as thumb:
        assert thumb.size == (THUMBNAIL_SIZE, THUMBNAIL_SIZE)


def test_the_thumbnail_is_dramatically_smaller():
    variant = ProductVariantFactory()
    image, original_size = make_image(variant.product)
    assert image.thumbnail.size < original_size / 5


def test_a_png_with_alpha_becomes_a_jpeg():
    """A PNG with an alpha channel cannot be saved as JPEG without an explicit convert,
    and product uploads do include PNGs."""
    from django.core.files.base import ContentFile

    variant = ProductVariantFactory()
    buffer = BytesIO()
    Image.new("RGBA", (800, 800), (10, 20, 30, 128)).save(buffer, format="PNG")
    image = ProductImage(product=variant.product)
    image.image.save("clear.png", ContentFile(buffer.getvalue()), save=False)
    image.save()

    assert image.thumbnail.name.endswith(".jpg")
    with Image.open(image.thumbnail) as thumb:
        assert thumb.mode == "RGB"


def test_saving_twice_does_not_rebuild_the_thumbnail():
    variant = ProductVariantFactory()
    image, _ = make_image(variant.product)
    first = image.thumbnail.name

    image.alt = "edited"
    image.save()

    assert image.thumbnail.name == first


def test_thumbnail_name_is_relative_to_upload_to():
    """`ProductImage.thumbnail` declares `upload_to="catalog/thumbs/"` and Django prepends
    it, so returning a full key here produced `catalog/thumbs/catalog/thumbs/…`."""
    assert thumbnail_name("catalog/products/slug/x.png") == "products/slug/x.jpg"
    assert not thumbnail_name("catalog/products/a.jpg").startswith("catalog/")


def test_an_unreadable_upload_leaves_the_thumbnail_blank_rather_than_raising():
    """Saving a product must not depend on Pillow's opinion of a file; the render path
    falls back to the full-size image, which is the behaviour that existed before."""
    from apps.catalog.thumbnails import build_thumbnail

    assert build_thumbnail(BytesIO(b"not an image")) is None


# ── which picture ───────────────────────────────────────────────────────────────────

def test_a_variant_tagged_image_wins_over_the_product_default():
    """Tagging a photo '200ml' says THIS is what the 200ml looks like. Showing the 50ml
    jar on a 200ml line is the confusion tagging exists to prevent."""
    variant = ProductVariantFactory()
    generic, _ = make_image(variant.product)
    generic.position = 0
    generic.save()

    tagged, _ = make_image(variant.product)
    tagged.variant = variant
    tagged.position = 5
    tagged.save()

    assert variant_image_path(variant) == tagged.thumbnail.name


def test_the_thumbnail_is_preferred_over_the_full_size_original():
    variant = ProductVariantFactory()
    image, _ = make_image(variant.product)
    assert variant_image_path(variant) == image.thumbnail.name
    assert "thumbs" in variant_image_path(variant)


def test_a_missing_thumbnail_falls_back_to_the_original():
    """Covers images uploaded before the field existed, and anything Pillow could not
    read. `.update()` rather than `.save()` deliberately: `save()` REGENERATES a blank
    thumbnail (which is the right behaviour — it makes the model self-heal — and is
    asserted below), so it cannot be used to construct this state."""
    variant = ProductVariantFactory()
    image, _ = make_image(variant.product)
    ProductImage.objects.filter(pk=image.pk).update(thumbnail="")
    image.refresh_from_db()

    assert variant_image_path(variant) == image.image.name
    assert "thumbs" not in variant_image_path(variant)


def test_saving_an_image_whose_thumbnail_went_missing_regenerates_it():
    variant = ProductVariantFactory()
    image, _ = make_image(variant.product)
    ProductImage.objects.filter(pk=image.pk).update(thumbnail="")
    image.refresh_from_db()

    image.save()

    assert image.thumbnail
    assert "thumbs" in image.thumbnail.name


def test_a_variant_with_no_images_resolves_to_nothing():
    assert variant_image_path(ProductVariantFactory()) == ""
    assert variant_image_path(None) == ""
    assert storage_url("") == ""


def test_alt_text_falls_back_to_the_product_name():
    """Most clients block remote images, so for many readers the alt string IS the
    picture — it has to say which product the row is."""
    variant = ProductVariantFactory()
    make_image(variant.product)
    assert variant_image_alt(variant) == variant.product.name


def test_storage_url_absolutises_a_relative_dev_path(settings):
    """An `<img src="/media/…">` inside an email resolves against the MAIL CLIENT's
    origin and renders broken."""
    settings.API_PUBLIC_URL = "https://api.example.com"
    url = storage_url("catalog/thumbs/products/x.jpg")
    assert url.startswith("https://api.example.com/")


def test_storage_url_leaves_an_absolute_cdn_url_alone(settings):
    from apps.catalog.images import absolutise

    settings.API_PUBLIC_URL = "https://api.example.com"
    cdn = "https://cdn.example.net/catalog/thumbs/x.jpg"
    assert absolutise(cdn) == cdn
