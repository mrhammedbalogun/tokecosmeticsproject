export const PLACEMENTS: { value: string; label: string; guide: string }[] = [
  { value: "hero", label: "Hero slide", guide: "Image 1920×1080 (or video mp4/webm, ≤60s, ≤80 MB — image becomes the poster). Title, subtitle and CTA render on the slide; 2+ slides make the slider rotate." },
  { value: "strip", label: "News marquee item", guide: "Text only — the title scrolls in the news bar; CTA URL makes it a link. No media needed." },
  { value: "category", label: "Shop-by-category tile", guide: "Image/video 900×1200 (3:4 portrait). Title is the pill label; CTA URL is the destination. Up to 4 tiles, ordered by sort." },
  { value: "concern", label: "Shop-by-concern tile", guide: "Image/video 1200×525 (16:7 wide). Title is the label; CTA URL the destination. Up to 3 tiles, ordered by sort." },
  { value: "feature", label: "Glow Set feature", guide: "Image/video 1400×1000. Title, tagline (the paragraph), CTA text + URL all show. One banner." },
  { value: "feature_nature", label: "tokè × natural tile", guide: "Image/video 1200×600. Subtitle is the small eyebrow, title the line under it. One banner." },
  { value: "feature_collection", label: "Toke Naturals tile", guide: "Image/video 1200×600. Subtitle eyebrow + title; CTA URL is where the tile links. One banner." },
  { value: "men", label: "Men section banner", guide: "Image/video 1200×1100. Subtitle = eyebrow, title, tagline, CTA text + URL. Products beside it come from the ‘men’ collection." },
  { value: "women", label: "Women section banner", guide: "Image/video 1200×1100. Same fields as Men; products from the ‘women’ collection." },
  { value: "babies", label: "Babies section banner", guide: "Image/video 1200×1100. Same fields as Men; products from the ‘babies’ collection." },
  { value: "tiktok", label: "TikTok section banner", guide: "Image/video 1300×900. Title, tagline, CTA text + URL. Products beside it come from best sellers." },
  { value: "trio", label: "Collections trio tile", guide: "Image/video 900×1200 (3:4). Title, tagline, CTA text + URL. Up to 3 tiles, ordered by sort." },
];

/** Banner shapes and the "is it showing?" question (Plan-19c). */

export interface BannerRow {
  id: number;
  title: string;
  subtitle: string;
  image: string | null;
  mobile_image: string | null;
  video: string | null;
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
