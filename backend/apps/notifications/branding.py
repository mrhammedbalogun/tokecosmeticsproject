"""The brand facts every email needs: logo, shop links, social accounts, footer copy.

WHY THIS IS INJECTED IN `send_email` AND NOT PASSED BY EACH CALLER
------------------------------------------------------------------
`render_to_string` is called WITHOUT a request (see send.py), and Django only runs
context processors for a request-bound render. So `settings` is unreachable from a
template here — `{{ FRONTEND_URL }}` in base.html would silently render as an empty
string, and an empty `src` is a broken image in every inbox that opens it.

There are ~20 templates and a dozen call sites across orders, accounts, referrals,
inventory and delivery. Threading the logo URL through all of them would mean any new
mail that forgot one line would ship a header with no logo. `send_email` is the single
choke point every one of them already passes through, so the shell is guaranteed to be
branded whatever the caller remembered to pass.

WHY THE ASSETS LIVE ON THE STOREFRONT
-------------------------------------
`storefront/public/email/*` is served by Vercel on the apex domain, already CDN-cached
and already the origin the recipient's client trusts for our images. The backend has no
static-file server in production (whitenoise serves the admin's own assets only), and
Resend does not host images. `EMAIL_ASSET_BASE_URL` exists so the assets can be moved
to a bucket later without touching a template.

Mail clients cache images by URL for months, so treat these filenames as permanent:
publish a new file rather than changing the bytes behind an existing one.
"""
from __future__ import annotations

from django.conf import settings

#: Order matters — it is the order they render in the footer, biggest audience first.
#: `label` is also the image's alt text, so it is what a reader with images blocked
#: sees and clicks. Keep it the plain platform name.
#:
#: KEEP IN STEP WITH `storefront/src/lib/social-links.ts`, which is the same list for the
#: website. Python cannot import TypeScript and vice versa, so the duplication is
#: unavoidable; each file is the single source for its own side.
#:
#: EVERY URL IS https, including Facebook — the owner's list gave that one as `http://`.
#: It is the same page (Facebook 301s the plaintext form), and an `http://` link costs a
#: redirect hop and reads as a downgrade to the scanners that score a message before an
#: inbox ever sees it.
SOCIAL_LINKS: tuple[tuple[str, str, str], ...] = (
    ("Instagram", "https://www.instagram.com/tokecosmetics_brand/", "social-instagram.png"),
    ("TikTok", "https://www.tiktok.com/@tokecosmetics", "social-tiktok.png"),
    ("Facebook", "https://www.facebook.com/tokecosmetics", "social-facebook.png"),
    ("YouTube", "https://www.youtube.com/@tokecosmetics", "social-youtube.png"),
)


def brand_context() -> dict:
    """Brand facts for the email shell. Merged UNDER the caller's context in `send_email`,
    so a template that genuinely needs a different value can still be passed one."""
    shop = settings.FRONTEND_URL.rstrip("/")
    assets = (getattr(settings, "EMAIL_ASSET_BASE_URL", "") or shop).rstrip("/")

    return {
        "brand_name": "Toke Cosmetics",
        "shop_url": shop,
        "logo_url": f"{assets}/email/logo.png",
        "socials": [
            {"label": label, "url": url, "icon": f"{assets}/email/{icon}"}
            for label, url, icon in SOCIAL_LINKS
        ],
        # Footer nav. Every one of these is a real code route on the storefront — the
        # `/page/*` CMS slugs are deliberately NOT here, because production has zero CMS
        # pages and each of those is a live 404 (see storefront Footer.tsx).
        "footer_links": [
            {"label": "Shop", "url": f"{shop}/products"},
            {"label": "Your account", "url": f"{shop}/account"},
            {"label": "Affiliates", "url": f"{shop}/affiliates"},
            {"label": "Contact us", "url": f"{shop}/contact-us"},
        ],
        "contact_url": f"{shop}/contact-us",
        # Footer link for STAFF and OPS mail, which overrides `footer_links` — a shop nav
        # row under a low-stock alert points the reader at the wrong application. Named
        # `admin_home_url` and not `admin_url`: the staff order alerts already carry an
        # `admin_url` that deep-links to the specific order, and shadowing it here would
        # send every "Open in admin" button to the dashboard instead.
        "admin_home_url": settings.ADMIN_URL.rstrip("/"),
        # The SAME address the mail is Reply-To'd to, deliberately: the footer's contact
        # link and the reply button have to land in one inbox, or a customer who uses the
        # one nobody watches is simply lost. The footer omits the line if it is ever blank
        # — printing an address nobody reads is worse than printing none.
        "support_email": getattr(settings, "EMAIL_REPLY_TO", "") or "",
    }
