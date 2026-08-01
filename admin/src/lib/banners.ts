/** Banner shapes and the "is it showing?" question (Plan-19c). */

export interface BannerRow {
  id: number;
  title: string;
  subtitle: string;
  image: string | null;
  mobile_image: string | null;
  cta_text: string;
  cta_url: string;
  placement: "hero" | "strip" | "category";
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
export function livePlacement(banners: BannerRow[], placement: BannerRow["placement"], now = new Date()) {
  return banners
    .filter((b) => b.placement === placement && bannerState(b, now) === "live")
    .sort((a, b) => a.sort - b.sort);
}
