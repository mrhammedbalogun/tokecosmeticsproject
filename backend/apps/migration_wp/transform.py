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
_BENEFIT_SPLIT_RE = re.compile(r"\s{2,}")
_TESTIMONIAL_SLOTS = (1, 2, 3)
_NBSP_RE = re.compile(r"(&nbsp;| )")


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
