"""Which picture represents a variant, and how to turn a stored path into a URL.

ONE ANSWER, SHARED. Checkout snapshots a line's picture into `OrderItem.image_path`, the
email templates render it, and the order API exposes it. Those paths must agree or a
customer's confirmation email shows a different photograph from their order page, so they
all come through here.

── PATHS ARE STORED, URLS ARE DERIVED ──────────────────────────────────────────────

`OrderItem.image_path` holds a STORAGE KEY (`catalog/thumbs/products/…jpg`), never a
finished URL. Two reasons, both learned the hard way:

1. **A URL freezes today's CDN hostname into the orders table forever.** This project has
   already moved media hosting once (local → S3 → CloudFront, see
   `config/settings/base.py`). Snapshot `https://<cdn>/…` and the next move silently
   breaks the picture in every historical order and every re-opened confirmation email.
   A key survives it; `default_storage.url()` answers with whatever is current.
2. **A URL does not fit.** `OrderItem.image_url` was a `URLField`, i.e. varchar(200),
   while `ProductImage.image` allows a 500-character path (`IMAGE_PATH_MAX`, widened
   because 39 imported images had already been truncated at 100). Writing a long CDN URL
   into it raises `DataError` from Postgres — measured, not theorised — and because the
   write happens inside `place_order`'s locked transaction that is a 500 handed to a
   customer at checkout. The field is now a `CharField(max_length=500)` holding a key.

── WHICH IMAGE ─────────────────────────────────────────────────────────────────────

A `ProductImage` may name a variant. If one does, it wins: tagging a photo "200ml" is
saying *this is what the 200ml looks like*, and showing the 50ml jar on a 200ml line is
the confusion tagging exists to prevent. Otherwise the product's first image by
`position` — the same one the storefront's product card shows, so the email matches the
page the customer bought from.

The THUMBNAIL is preferred over the original wherever one exists: 256px square at ~20KB
against a 549KB average full-size original. `apps/catalog/thumbnails.py` explains why that
matters enough to have a pipeline. A blank thumbnail falls back to the original, so an
image Pillow could not read still shows something.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)


def absolutise(url: str | None) -> str:
    """An absolute URL for `url`, or "" if there is nothing to absolutise.

    Anything already carrying a scheme is returned untouched — that is the production
    (CloudFront) path and the overwhelmingly common one. A protocol-relative `//host/…`
    is also left alone; it is already host-absolute and mail clients resolve it against
    https in practice.
    """
    if not url:
        return ""
    if url.startswith(("http://", "https://", "//")):
        return url
    return f"{settings.API_PUBLIC_URL.rstrip('/')}/{url.lstrip('/')}"


def storage_url(path: str | None) -> str:
    """An absolute URL for a stored key, or "" when there is nothing to point at.

    In production the storage backend answers with the CloudFront domain, so this is
    already absolute; in dev it answers `/media/…` and `absolutise` finishes the job.
    An `<img src="/media/…">` inside an email resolves against the MAIL CLIENT's origin
    and renders broken — a bug that looks fine in every local test and is found by a
    customer.
    """
    if not path:
        return ""
    try:
        return absolutise(default_storage.url(path))
    except Exception:  # noqa: BLE001 — a storage backend that cannot build a URL
        logger.warning("could not build a URL for %r", path)
        return ""


def _first_image(variant):
    """The `ProductImage` that represents `variant`, or None.

    Uses `.all()[:1]` rather than `.first()` so a caller that has prefetched
    `variant__images` / `variant__product__images` is served from the prefetch cache
    instead of issuing a fresh query per line — which matters because this is called from
    inside checkout's locked block.
    """
    if variant is None:
        return None
    own = list(variant.images.all()[:1])
    if own:
        return own[0]
    product = list(variant.product.images.all()[:1])
    return product[0] if product else None


def variant_image_path(variant) -> str:
    """The storage key to snapshot for `variant`, preferring its thumbnail. "" if none.

    NARROW EXCEPTION HANDLING ON PURPOSE. This is called from inside `place_order`'s
    atomic block, where swallowing a `DatabaseError` would leave the transaction aborted
    and make the NEXT query fail with a misleading "current transaction is aborted".
    Only the attribute/value errors that a half-configured image can raise are caught;
    database errors propagate to the caller that can actually roll back.
    """
    try:
        image = _first_image(variant)
    except (AttributeError, ValueError):
        return ""
    if image is None:
        return ""
    return image.thumbnail.name if image.thumbnail else image.image.name


def variant_image_alt(variant) -> str:
    """Alt text for the picture. Falls back to the product name, because most mail
    clients block remote images by default — for those readers the alt string IS the
    picture, so it has to say which product the row is."""
    try:
        image = _first_image(variant)
        if image is not None and image.alt:
            return image.alt
        return variant.product.name if variant is not None else ""
    except (AttributeError, ValueError):
        return ""
