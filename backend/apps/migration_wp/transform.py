"""Pure transforms from WordPress shapes to platform shapes.

Every function here takes plain data and returns plain data — no Django models,
no database, no network. That keeps the migration's real logic unit-testable
without a MySQL service in CI.
"""
from __future__ import annotations

import html as html_lib
import re

# Editor paste artifacts: <p data-start="162" data-end="542">
_DATA_ATTR_RE = re.compile(r'\s+data-(?:start|end)="[^"]*"')
_NBSP_RE = re.compile(r"(&nbsp;| )")


_BENEFIT_SPLIT_RE = re.compile(r"\s{2,}")
_TESTIMONIAL_SLOTS = (1, 2, 3)


def clean_description(html: str | None) -> str:
    """Strip editor artifacts from WooCommerce product HTML.

    The content is human-written prose in simple HTML (verified 2026-07-25:
    no Elementor, no shortcodes, no embedded images). Only two artifacts need
    removing, and real markup must survive untouched.
    """
    if not html:
        return ""
    out = _DATA_ATTR_RE.sub("", html)
    out = _NBSP_RE.sub(" ", out)
    return out.strip()


def parse_benefits(raw: str | None) -> list[str]:
    """Split the ACF `Benefits` blob into individual benefit sentences.

    Source format is one string with sentences separated by runs of 2+ spaces.
    """
    if not raw:
        return []
    return [part.strip() for part in _BENEFIT_SPLIT_RE.split(raw.strip()) if part.strip()]


def append_benefits(description: str, benefits: list[str]) -> str:
    """Append benefits as a bulleted list so they render in the PDP Description
    accordion (storefront/src/components/product/PdpAccordions.tsx) without
    needing a new storefront section.
    """
    if not benefits:
        return description
    items = "".join(f"<li>{html_lib.escape(b)}</li>" for b in benefits)
    return f"{description}\n<h3>Benefits</h3>\n<ul>{items}</ul>"


def parse_usps(meta: dict[str, str]) -> list[str]:
    """Main USP first, then product_usp_1..4 in order. Blanks dropped."""
    keys = ["product_main_usp"] + [f"product_usp_{i}" for i in range(1, 5)]
    return [meta[k].strip() for k in keys if (meta.get(k) or "").strip()]


def parse_testimonials(meta: dict[str, str]) -> list[dict]:
    """Group the flat Testimonial_N_* ACF keys into records.

    An entry with no review text is not a testimonial — skip it. These become
    Product.testimonials and must NEVER become Review rows: the source carries
    no rating, and inventing one would publish a fabricated schema.org
    aggregateRating (see storefront/src/lib/seo.ts:154).
    """
    out: list[dict] = []
    for i in _TESTIMONIAL_SLOTS:
        text = (meta.get(f"Testimonial_{i}_Review_Text") or "").strip()
        if not text:
            continue
        raw_qty = (meta.get(f"Testimonial_{i}_Number_of_Item_Bought") or "").strip()
        try:
            qty = int(raw_qty)
        except ValueError:
            qty = None
        out.append(
            {
                "name": (meta.get(f"Testimonial_{i}_Customer_Name") or "").strip(),
                "text": text,
                "skin_concern": (meta.get(f"Testimonial_{i}_Skin_Concern") or "").strip(),
                "qty_bought": qty,
            }
        )
    return out


SKU_PREFIX = "TC-WP-"


def generate_sku(existing_sku: str | None, wp_id: int) -> str:
    """Real SKU if WooCommerce has one, else a generated stable fallback.

    Only 1 SKU exists across the whole catalogue (audited 2026-07-25), so the
    fallback is the primary path. `wp_id` MUST be the ID of the row the variant
    represents — the variation's post ID for variable products, the product's
    post ID for simple ones. Passing a parent ID for variations collides.
    """
    if existing_sku and existing_sku.strip():
        return existing_sku.strip()
    return f"{SKU_PREFIX}{wp_id}"


def _axis_label(axis: str) -> str:
    """`attribute_pa_product-size` -> `Product Size`; `attribute_shea-variant` -> `Shea Variant`."""
    name = axis[len("attribute_"):] if axis.startswith("attribute_") else axis
    if name.startswith("pa_"):
        name = name[3:]
    name = name.replace("-", " ").replace("_", " ")
    return " ".join(w[:1].upper() + w[1:] for w in name.split())


def parse_option_values(
    attributes: dict[str, str], term_names: dict[tuple[str, str], str]
) -> dict[str, str]:
    """Build ProductVariant.option_values from a variation's attribute_* meta.

    `term_names` maps (taxonomy, term_slug) -> human term name, so taxonomy-backed
    axes show "50 ml" rather than the slug. Non-taxonomy axes (shea-variant) and
    unmapped slugs fall back to the raw value.

    Assumes axis labels are distinct after normalisation: two different
    `attribute_*` keys that normalise to the same label (e.g. via case or
    separator differences) will silently clobber each other in the output dict.
    """
    out: dict[str, str] = {}
    for axis, value in attributes.items():
        if not value or not value.strip():
            continue
        taxonomy = axis[len("attribute_"):] if axis.startswith("attribute_") else axis
        out[_axis_label(axis)] = term_names.get((taxonomy, value), value)
    return out


_ACF_IMAGE_KEYS = [f"Small_Image_{i}" for i in range(1, 5)] + [
    f"Medium_Image_{i}" for i in range(1, 3)
]


def collect_attachment_ids(product_ids: list[int], meta: dict[int, dict[str, str]]) -> list[int]:
    """Thumbnail + gallery + the ACF Small_Image_*/Medium_Image_* slots.

    The ACF image fields hold attachment IDs, not URLs (verified 2026-07-25).
    Pure logic over WooCommerce/ACF naming and comma-separated gallery format —
    no SQL, no ORM — so it belongs alongside the rest of this module's meta
    parsing rather than living in the extract command.
    """
    ids: set[int] = set()
    for pid in product_ids:
        m = meta.get(pid, {})
        if (m.get("_thumbnail_id") or "").strip().isdigit():
            ids.add(int(m["_thumbnail_id"]))
        gallery = (m.get("_product_image_gallery") or "").strip()
        for part in gallery.split(","):
            if part.strip().isdigit():
                ids.add(int(part.strip()))
        for key in _ACF_IMAGE_KEYS:
            val = (m.get(key) or "").strip()
            if val.isdigit():
                ids.add(int(val))
    return sorted(ids)
