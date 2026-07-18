# Toke Cosmetics — Storefront Design Direction

> Source: Hammed's design brief (`StoreFrontLandingPageDesignPrompt.txt`, 2026-07-18).
> This document is the authority for all storefront visual/UX decisions (Plans 12–15).
> It **amends Plan-12 D1**: Hammed's brief explicitly adds soft gold as a secondary
> accent alongside the Toke forest green — that is his sign-off on the palette.

## Brand feel

Premium international skincare with African identity. Benchmarks: **Rhode, Aesop,
Fenty Skin, Typology, The Ordinary, Sephora**. The homepage must immediately read:
premium skincare · trust · luxury · natural ingredients · science-backed ·
African beauty · international quality.

Audience: primary Nigeria; secondary UK/US/Canada/international. Must appeal to
Black women and men, families, mothers, babies, teenagers — without clutter.

## Style rules

**Do:** large typography, generous white space, rounded corners, soft shadows,
large photography, editorial layouts, smooth restrained animation, glassmorphism
only where it earns its place.

**Avoid:** generic ecommerce layouts, busy sections, too many colors, heavy
borders, cheap-looking buttons, WordPress-looking components, oversaturated color.

## Palette (authoritative — resolves Plan-12 D1)

| Token | Role | Value |
|---|---|---|
| Cream | page background | `#FBF9F5` |
| Warm beige | alternate section background, cards | `#F1EAE0` |
| Surface white | cards, drawers | `#FFFFFF` |
| Dark charcoal | primary text | `#1A1A1A` |
| Ink soft | secondary text | `#6B6862` |
| Deep forest green | primary accent — buttons, links, active states | `#1C7A3E` (dark hover `#145F30`) |
| Leaf green | subtle highlight (from logo rim) | `#8CC63F` — use sparingly |
| Soft gold | secondary accent — badges, ratings, small luxury details | `#C9A227` (muted, never saturated) |

Gold is a *seasoning*, not a second brand color: ratings stars, "bestseller"
badges, thin decorative rules. Green owns every interactive element.

## Typography

- Display / headings: **Playfair Display** (serif, editorial).
- Body / UI: **Inter**.
- Large headline sizes on heroes; airy line-height; no more than two families.

## Motion

Framer Motion (added in Plan-13 when real sections are built — the Plan-12 shell
stays dependency-light for Lighthouse ≥95). Vocabulary: fade-up on scroll, subtle
image zoom on hover, hover lift on cards, parallax hero, elegant page-load fade.
**No excessive animation** — every effect must feel calm and expensive.

## Homepage structure (Plan-13 build order)

1. Announcement bar — rotating messages (free NG delivery threshold, international
   shipping, dermatologist recommended, secure worldwide checkout)
2. Sticky navigation that shrinks elegantly on scroll — logo, Shop, Collections,
   Skin Concerns, Ingredients, About, Blog, Community, Rewards, search, wishlist,
   account, cart, country/currency selector
3. Full-width cinematic hero — large lifestyle photography, headline like
   "Healthy Skin Begins Here.", CTAs **Shop Now** + **Take Skin Quiz**, subtle motion
4. Featured categories — image cards (Face, Body, Hair, Kids, Babies, Men, Family)
5. Shop by skin concern — grid (Acne, Hyperpigmentation, Dry, Oily, Sensitive,
   Eczema, Dark Spots, Uneven Tone)
6. Brand story — split editorial: natural ingredients, science-backed, made for
   melanin-rich skin, trusted worldwide
7. Best sellers — product carousel (image, rating, price, discount, quick add, wishlist)
8. Featured collection banner — large promo (e.g. "Glow Naturally")
9. New arrivals — responsive grid
10. Why choose Toke — icon cards (dermatologist approved, natural, cruelty free,
    worldwide shipping, secure payments, money-back, fast delivery)
11. Customer reviews — premium testimonial carousel with avatars
12. Instagram / community — masonry, lifestyle + UGC
13. Educational — latest skincare articles
14. Newsletter — minimal, elegant CTA
15. Footer — large: shop/company/support/wholesale/affiliate/rewards/shipping/
    returns/privacy/terms, newsletter, socials, payment methods, country + currency

## Non-negotiables (all storefront pages)

- Desktop-first design, flawless down to mobile; no horizontal scroll.
- WCAG AA: keyboard nav, heading hierarchy, ARIA labels, visible focus, contrast.
- SEO: semantic HTML, metadata + Open Graph + schema.org, canonical URLs, alt text.
- Performance: Server Components by default, lazy loading, optimized images,
  dynamic imports. Lighthouse ≥ 95 target on every page.
- Component base: shadcn/ui-style primitives (Cards, Buttons, Carousel, Accordion,
  Dialog, Drawer, Sheet, Tabs, Badges, Tooltips, Popover) styled to this palette.
