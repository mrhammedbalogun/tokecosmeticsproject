# Landing redesign v1 — APPROVED by Hammed 2026-08-04

Reference: `landing-redesign-v1.html` (the reviewed artifact, final state). Mirrors
production tokecosmetics.com sectioning in the new brand language. Build into
`storefront/` homepage.

Approved decisions, in review order:
1. **Marquee announcement bar** — multiple news items scroll continuously, pause on
   hover, admin-managed (CMS announcements), reduced-motion → static first item.
2. **Nav**: Home · All Products · Shop by Category · Skin Quiz · Blog.
3. **Hero slider**: full-bleed, SQUARE corners, `min-h-[78vh]` (current Hero.tsx height).
   Slides are image banners OR video, from admin — NO media-type tags shown to customers.
   Numbered title tabs (01/02/03) with autoplay progress bar + arrows.
4. Sections in order: categories (Best Sellers/Skin/Hair/Babies) → concerns strip
   (Acne/Hyperpigmentation/Dry Skin) → Glow Set split feature + Toke Naturals stack →
   Best Sellers → **New for Men → For Women (mirrored) → For Babies** (big tile +
   2×2 products each, alternating sides) → New Arrivals headed **"Natural Products"** →
   TikTok Made Me Try It → Kids/Men's/Family trio → Journal → **Google reviews** → footer.
5. **Product cards**: tall 1:1 image, slim footer = name (one line, ellipsis) +
   price + Add. NO category line, NO shade dots on landing cards.
6. **Google reviews**: header rating+count auto from Places API; the 4 featured cards
   CURATED in admin, each with its Google review share-link (click → exact review).
   Ruled during review: Places API has no per-review permalink, hence curation.
7. Logo: use the real Toke logo from the current storefront (not the mockup's circle).
