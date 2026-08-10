/**
 * The homepage placement catalogue (Plan-19c, reworked for the section-mirror editor).
 *
 * Each spec describes one storefront tile placement WELL ENOUGH TO EDIT IT BLIND: which
 * Banner fields the tile actually renders (with the storefront's own vocabulary — "Pill
 * label", not "title"), the artwork shape, how many tiles the section holds, and the
 * built-in content a slot falls back to. The specs mirror the storefront components
 * (`storefront/src/components/home/*`); if a section's fields or defaults change there,
 * change them here, because this file is what the admin promises the shop will show.
 */

export type BannerField = "title" | "subtitle" | "tagline" | "cta_text" | "cta_url";

export interface PlacementSpec {
  value: string;
  /** Section / tile name as the admin shows it. */
  label: string;
  /** The artwork cheat-sheet shown in the editor. */
  guide: string;
  /** The fields this tile renders, labelled the way the tile uses them. */
  fields: { key: BannerField; label: string; hint?: string }[];
  /** false for the text-only news marquee. */
  media: boolean;
  /** Tailwind aspect class matching the storefront tile, so thumbnails keep its shape. */
  aspect: string;
  /**
   * Fixed tile count (the storefront maps CMS banners onto exactly this many slots,
   * in sort order) or null for as-many-as-you-like (hero slides, news items).
   */
  slots: number | null;
  /**
   * The storefront's built-ins. For fixed-slot sections, per slot: an empty slot keeps
   * its own built-in. For unlimited sections the semantics differ — the built-ins show
   * only while the section has NO live banners at all; the first live one replaces the
   * whole set.
   */
  defaults: Partial<Record<BannerField, string>>[];
}

export const PLACEMENTS: PlacementSpec[] = [
  {
    value: "strip",
    label: "News marquee",
    guide: "Text only — the message scrolls in the news bar; a link makes it clickable. No artwork.",
    fields: [
      { key: "title", label: "Message" },
      { key: "cta_url", label: "Link (optional)", hint: "e.g. /products?collection=best-sellers" },
    ],
    media: false,
    aspect: "",
    slots: null,
    defaults: [
      { title: "Free delivery in Nigeria on orders over ₦50,000" },
      { title: "Worldwide shipping — UK · US · Canada · everywhere" },
      { title: "Dermatologist recommended, made for melanin-rich skin" },
      { title: "Secure worldwide checkout" },
    ],
  },
  {
    value: "hero",
    label: "Hero slide",
    // Videos bypass the platform's request cap entirely (direct-to-S3, 2026-08-09), so
    // the ceiling is the API's 128 MB guard — see lib/video.ts.
    guide: "Image 1920×1080, or mp4/webm up to 128 MB (the image becomes the poster). A looping video should be under 6 MB — it downloads for every visitor. 2+ slides make the slider rotate.",
    fields: [
      { key: "subtitle", label: "Eyebrow", hint: "The small line above the headline." },
      { key: "title", label: "Headline" },
      { key: "cta_text", label: "Button text" },
      { key: "cta_url", label: "Button link" },
    ],
    media: true,
    aspect: "aspect-video",
    slots: null,
    defaults: [{ subtitle: "Premium African skincare", title: "Healthy Skin Begins Here." }],
  },
  {
    value: "category",
    label: "Shop-by-category tile",
    guide: "Image/video 900×1200 (3:4 portrait).",
    fields: [
      { key: "title", label: "Pill label" },
      { key: "cta_url", label: "Tile link" },
    ],
    media: true,
    aspect: "aspect-[3/4]",
    slots: 4,
    defaults: [
      { title: "Best Sellers", cta_url: "/products?collection=best-sellers" },
      { title: "Skin", cta_url: "/products" },
      { title: "Hair", cta_url: "/products?q=hair" },
      { title: "Babies", cta_url: "/products?collection=babies" },
    ],
  },
  {
    value: "concern",
    label: "Shop-by-concern tile",
    guide: "Image/video 1200×525 (16:7 wide).",
    fields: [
      { key: "title", label: "Label" },
      { key: "cta_url", label: "Tile link" },
    ],
    media: true,
    aspect: "aspect-[16/7]",
    slots: 3,
    defaults: [
      { title: "Acne", cta_url: "/products?q=acne" },
      { title: "Hyperpigmentation", cta_url: "/products?q=brightening" },
      { title: "Dry Skin", cta_url: "/products?q=hydrating" },
    ],
  },
  {
    value: "feature",
    label: "Glow Set feature",
    guide: "Image/video 1400×1000.",
    fields: [
      { key: "title", label: "Heading" },
      { key: "tagline", label: "Paragraph" },
      { key: "cta_text", label: "Button text" },
      { key: "cta_url", label: "Button link" },
    ],
    media: true,
    aspect: "aspect-[7/5]",
    slots: 1,
    defaults: [
      {
        title: "The Glow Set",
        tagline:
          "Brightening oil, daily facial wash and repair cream — the routine our community swears by.",
        cta_text: "Shop the Set",
        cta_url: "/products?collection=best-sellers",
      },
    ],
  },
  {
    value: "feature_nature",
    label: "tokè × natural tile",
    guide: "Image/video 1200×600. This tile is not a link — it sets the mood beside the Glow Set.",
    fields: [
      { key: "subtitle", label: "Eyebrow" },
      { key: "title", label: "Heading" },
    ],
    media: true,
    aspect: "aspect-[2/1]",
    slots: 1,
    defaults: [{ subtitle: "tokè × natural", title: "Grown from nature, proven by science" }],
  },
  {
    value: "feature_collection",
    label: "Toke Naturals tile",
    guide: "Image/video 1200×600.",
    fields: [
      { key: "subtitle", label: "Eyebrow" },
      { key: "title", label: "Heading" },
      { key: "cta_url", label: "Tile link" },
    ],
    media: true,
    aspect: "aspect-[2/1]",
    slots: 1,
    defaults: [{ subtitle: "Collection", title: "Toke Naturals", cta_url: "/products?q=natural" }],
  },
  {
    value: "men",
    label: "Men section banner",
    guide: "Image/video 1200×1100. The products beside it come from the ‘men’ collection.",
    fields: [
      { key: "subtitle", label: "Eyebrow" },
      { key: "title", label: "Heading" },
      { key: "tagline", label: "Line under the heading" },
      { key: "cta_text", label: "Button text" },
      { key: "cta_url", label: "Button link" },
    ],
    media: true,
    aspect: "aspect-[12/11]",
    slots: 1,
    defaults: [
      {
        subtitle: "New Formulas",
        title: "New for Men",
        tagline: "Made for men's skin",
        cta_text: "Shop now",
        cta_url: "/products?collection=men",
      },
    ],
  },
  {
    value: "women",
    label: "Women section banner",
    guide: "Image/video 1200×1100. The products beside it come from the ‘women’ collection.",
    fields: [
      { key: "subtitle", label: "Eyebrow" },
      { key: "title", label: "Heading" },
      { key: "tagline", label: "Line under the heading" },
      { key: "cta_text", label: "Button text" },
      { key: "cta_url", label: "Button link" },
    ],
    media: true,
    aspect: "aspect-[12/11]",
    slots: 1,
    defaults: [
      {
        subtitle: "Radiance Rituals",
        title: "For Women",
        tagline: "Glow that starts with care",
        cta_text: "Shop now",
        cta_url: "/products?collection=women",
      },
    ],
  },
  {
    value: "babies",
    label: "Babies section banner",
    guide: "Image/video 1200×1100. The products beside it come from the ‘babies’ collection.",
    fields: [
      { key: "subtitle", label: "Eyebrow" },
      { key: "title", label: "Heading" },
      { key: "tagline", label: "Line under the heading" },
      { key: "cta_text", label: "Button text" },
      { key: "cta_url", label: "Button link" },
    ],
    media: true,
    aspect: "aspect-[12/11]",
    slots: 1,
    defaults: [
      {
        subtitle: "Gentle by Design",
        title: "For Babies",
        tagline: "Soft care for the softest skin",
        cta_text: "Shop now",
        cta_url: "/products?collection=babies",
      },
    ],
  },
  {
    value: "tiktok",
    label: "TikTok section banner",
    guide: "Image/video 1300×900. The products beside it come from best sellers.",
    fields: [
      { key: "title", label: "Heading" },
      { key: "tagline", label: "Line under the heading" },
      { key: "cta_text", label: "Button text" },
      { key: "cta_url", label: "Button link" },
    ],
    media: true,
    aspect: "aspect-[13/9]",
    slots: 1,
    defaults: [
      {
        title: "TikTok Made Me Try It",
        tagline: "The community favourites, as seen on your feed.",
        cta_text: "Shop Now",
        cta_url: "/products?collection=best-sellers",
      },
    ],
  },
  {
    value: "trio",
    label: "Collections trio tile",
    guide: "Image/video 900×1200 (3:4 portrait).",
    fields: [
      { key: "title", label: "Heading" },
      { key: "tagline", label: "Line under the heading" },
      { key: "cta_text", label: "Button text" },
      { key: "cta_url", label: "Button link" },
    ],
    media: true,
    aspect: "aspect-[3/4]",
    slots: 3,
    defaults: [
      {
        title: "Kids' Collection",
        tagline: "Made comfortable for growing skin.",
        cta_text: "Explore",
        cta_url: "/products?collection=babies",
      },
      {
        title: "Men's Essentials",
        tagline: "Built for strength, made to refresh.",
        cta_text: "Explore",
        cta_url: "/products?collection=men",
      },
      {
        title: "Family",
        tagline: "Together in care, together in glow.",
        cta_text: "Explore",
        cta_url: "/products",
      },
    ],
  },
];

export function placementSpec(value: string): PlacementSpec {
  const spec = PLACEMENTS.find((p) => p.value === value);
  if (!spec) throw new Error(`Unknown banner placement: ${value}`);
  return spec;
}

/** Banner shapes and the "is it showing?" question (Plan-19c). */

export interface BannerRow {
  id: number;
  title: string;
  subtitle: string;
  image: string | null;
  mobile_image: string | null;
  video: string | null;
  /** "loop" autoplays silently on the storefront; "click" shows the poster with a play
   * button. The server defaults to loop, so older rows behave as they always did. */
  video_mode: "loop" | "click";
  tagline: string;
  cta_text: string;
  cta_url: string;
  placement: string;
  sort: number;
  starts_at: string | null;
  ends_at: string | null;
  is_active: boolean;
  countries: string[];
  updated_at: string;
}

/** A market the store sells into, as the geo-targeting picker needs it. */
export interface CountryOption {
  code: string;
  name: string;
}

export type BannerState = "live" | "scheduled" | "ended" | "off";

/**
 * What a banner is doing right now.
 *
 * The backend decides this for real — `Banner.is_live` filters the public payload, so a
 * banner outside its window never reaches a browser. This mirrors that logic for the
 * admin list, because "active" is a checkbox and a marketer needs to know the difference
 * between ticked-and-showing and ticked-but-starts-Friday at a glance.
 */
export function bannerState(banner: BannerRow, now = new Date()): BannerState {
  if (!banner.is_active) return "off";
  if (banner.starts_at && new Date(banner.starts_at) > now) return "scheduled";
  if (banner.ends_at && new Date(banner.ends_at) < now) return "ended";
  return "live";
}

/** Live banners in a placement, in the order the storefront will show them. */
export function livePlacement(banners: BannerRow[], placement: string, now = new Date()) {
  return banners
    .filter((b) => b.placement === placement && bannerState(b, now) === "live")
    .sort((a, b) => a.sort - b.sort);
}

/** Every banner in a placement, in sort order — the lineup the editor manages. */
export function placementBanners(banners: BannerRow[], placement: string) {
  return banners.filter((b) => b.placement === placement).sort((a, b) => a.sort - b.sort);
}
