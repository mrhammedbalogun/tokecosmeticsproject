"""HTML sanitisation for staff-authored content rendered by the storefront.

── WHY THIS EXISTS IN PLAN-19 AND NOT PLAN-25 ──────────────────────────────────────

The storefront renders stored HTML through `dangerouslySetInnerHTML`
(`components/product/PdpAccordions.tsx:23`), and the comment four lines above states the
premise the code was written on: *"`description` is backend-authored rich HTML (trusted
admin content)."*

That was true while the only author was the owner. Plan-19 adds `cms.Page.body`, authored
by the `Content` role — which is deliberately NOT trusted with orders or products. The
sentence stops being true in the same release that adds the field, and the consequence is
script execution on the storefront's origin, which is where customers type card details.
So the sanitiser ships with the model rather than in Plan-25's sweep.

── nh3, NOT bleach ─────────────────────────────────────────────────────────────────

The master spec names `bleach`. It has been unmaintained since 2023 and its own README
points elsewhere. `nh3` is the maintained Rust `ammonia` binding, and it is strict by
default: unknown tags are dropped, `javascript:` URLs are removed, and attributes must be
allow-listed per tag.

── SANITISE ON WRITE, NOT ON READ ──────────────────────────────────────────────────

Cleaning on the way in means the database holds only safe HTML, so every reader — the
storefront, a future mobile app, an export — is safe without repeating the rule. The cost
is that a mistake in the allow-list is baked into stored rows; that is why the original
submission is kept alongside (`Page.body_source`) and the rendered field is derived.
"""
import nh3

# Deliberately small. This is policy prose and product copy: headings, paragraphs, lists,
# emphasis, links, tables and images. Everything structural or scriptable is absent —
# there is no <script>, <style>, <iframe>, <form>, <input> or <object> here, and adding
# one is a security decision rather than a formatting one.
ALLOWED_TAGS: set[str] = {
    "p", "br", "hr",
    "h2", "h3", "h4",
    "strong", "b", "em", "i", "u", "s", "sub", "sup",
    "ul", "ol", "li",
    "blockquote", "code", "pre",
    "a", "img",
    "table", "thead", "tbody", "tr", "th", "td",
    "span", "div",
}

ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    # `rel` is ABSENT deliberately, and nh3 enforces that: it refuses to accept `rel` in
    # this list while `link_rel` is set below, because it writes the attribute itself. That
    # is the safer arrangement — an author cannot clear the `noopener` that stops a
    # `target="_blank"` link from reaching back through `window.opener`.
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title", "width", "height", "loading"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan"},
    # `class` is allowed nowhere: the storefront's own utility classes would let an author
    # restyle the page around the content, and none of this copy needs to.
}

# `nh3` strips any scheme not listed. `mailto` and `tel` matter for a Contact page.
ALLOWED_SCHEMES: set[str] = {"http", "https", "mailto", "tel"}


def clean_html(value: str | None) -> str:
    """Return `value` with everything outside the allow-list removed.

    Link rel: `nh3` rewrites `rel` on links that open in a new tab, which closes the
    reverse-tabnabbing hole without the author having to know it exists.
    """
    if not value:
        return ""
    return nh3.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes={tag: set(attrs) for tag, attrs in ALLOWED_ATTRIBUTES.items()},
        url_schemes=ALLOWED_SCHEMES,
        link_rel="noopener noreferrer",
    )
