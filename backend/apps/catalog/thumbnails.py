"""Square thumbnails for product images.

WHY THIS EXISTS. The catalogue holds full-resolution photography — sampled across
production, an average of 549KB and a maximum of 1.9MB per image. That is correct for a
product page, where Next's image optimizer resizes on the fly, and wrong everywhere the
optimizer is absent. Two places it is absent:

1. **Email.** A mail client fetches whatever `src` says and no proxy resizes it (Gmail's
   image proxy caches, it does not resample). A three-line order emailed with full-size
   photography costs the reader ~1.6MB to render three 64-pixel squares — paid for by a
   customer on Nigerian mobile data, on every order, and again by every staff and
   external subscriber.
2. **Outlook.** Its Word rendering engine ignores `object-fit`, so a non-square photo
   forced to 64x64 by width/height attributes is DISTORTED rather than cropped. Cropping
   server-side is the only fix that reaches that client.

── SQUARE, CENTRE-CROPPED, AT ONE SIZE ─────────────────────────────────────────────

`THUMBNAIL_SIZE` is 256px for a 64px display box: 2x for retina, with headroom for the
admin list. One size rather than a set, because a second size doubles the storage and the
backfill for a case nobody has yet.

Centre-cropped rather than letterboxed. Product photography here is a jar or bottle
centred on a plain background, so the centre is the subject; a letterboxed thumbnail would
render as a small object marooned in white space at 64px.

JPEG at quality 82, not WebP: Outlook's engine does not decode WebP, and this pipeline
exists largely to serve Outlook properly. RGB conversion is explicit because a PNG with
alpha cannot be saved as JPEG, and product uploads do include PNGs.

IDEMPOTENT AND NON-FATAL. `ensure_thumbnail` returns False and logs rather than raising if
Pillow cannot read the file — a corrupt or exotic upload must not break saving a product,
and the render path falls back to the full-size image, which is exactly today's behaviour.
"""
from __future__ import annotations

import logging
from io import BytesIO

from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

THUMBNAIL_SIZE = 256
THUMBNAIL_QUALITY = 82


def thumbnail_name(source_name: str) -> str:
    """`catalog/products/slug/x.png` -> `products/slug/x.jpg`.

    RELATIVE TO `upload_to`, NOT AN ABSOLUTE KEY. `ProductImage.thumbnail` declares
    `upload_to="catalog/thumbs/"` and Django prepends it to whatever name it is handed, so
    returning a full key here produced `catalog/thumbs/catalog/thumbs/products/…` —
    measured, not theorised. The `catalog/` prefix is stripped for the same reason: it is
    already inside `upload_to`.

    The result mirrors the source path under the thumbnail prefix, so a thumbnail is
    always traceable to its original, and it stays under `catalog/*` — which is the exact
    scope of the CloudFront behaviour, so no infrastructure change is needed to serve it.
    """
    stem = source_name.rsplit(".", 1)[0]
    for prefix in ("catalog/thumbs/", "catalog/"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    return f"{stem}.jpg"


def build_thumbnail(fileobj) -> ContentFile | None:
    """A square centre-cropped JPEG, or None if the source cannot be read."""
    from PIL import Image, ImageOps

    try:
        fileobj.seek(0)
        with Image.open(fileobj) as img:
            # EXIF orientation first: phone photos are frequently stored rotated, and
            # cropping before honouring it crops the wrong edges.
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            square = ImageOps.fit(
                img, (THUMBNAIL_SIZE, THUMBNAIL_SIZE), method=Image.LANCZOS, centering=(0.5, 0.5)
            )
            buffer = BytesIO()
            square.save(buffer, format="JPEG", quality=THUMBNAIL_QUALITY, optimize=True)
            return ContentFile(buffer.getvalue())
    except Exception:  # noqa: BLE001 — see module docstring
        logger.exception("could not build a thumbnail")
        return None


def ensure_thumbnail(image_field_file, thumbnail_field_file, *, force: bool = False) -> bool:
    """Generate `thumbnail_field_file` from `image_field_file` if it is missing.

    Returns whether one was written. Does NOT save the model — the caller decides, so this
    works from both a `save()` override and a bulk backfill without one fighting the other.
    """
    if not image_field_file:
        return False
    if thumbnail_field_file and not force:
        return False

    content = build_thumbnail(image_field_file)
    if content is None:
        return False
    thumbnail_field_file.save(thumbnail_name(image_field_file.name), content, save=False)
    return True
