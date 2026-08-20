/** Shared row types for the delivery-partner feature (Plan-39): the partner portal
 * (`/partner`) and the staff oversight page (`/settings/partners`) render the same
 * backend rows, so the shapes live once, here. */

export interface PartnerZoneRow {
  id: number;
  lga_region: number;
  lga_name: string;
  /** The LGA's parent state — read-only, for grouping and for preselecting the
   * state half of the state → LGA cascade when editing. */
  state_id: number;
  state_name: string;
  lcda_name: string;
  areas_covered: string;
  dispatch_zone: string;
  /** null = "the partner has not set a price yet" — the row never reaches checkout. */
  price: string | null;
  min_days: number;
  max_days: number;
  is_active: boolean;
  updated_at: string;
}

/** The staff serializer additionally names the partner on each zone row. */
export interface AdminPartnerZoneRow extends PartnerZoneRow {
  partner: number;
  partner_name: string;
}

/** One entry of either half of the state → LGA cascade — both endpoints answer
 * with the same `{id, name}` shape. */
export interface PartnerRegionOption {
  id: number;
  name: string;
}

/** @deprecated older name for {@link PartnerRegionOption}, kept for existing imports. */
export type PartnerLgaOption = PartnerRegionOption;

export interface PartnerMe {
  name: string;
  code: string;
  email: string;
}

export interface DeliveryPartnerRow {
  id: number;
  name: string;
  code: string;
  email: string;
  is_active: boolean;
  zone_count: number;
  live_zone_count: number;
  /** False until staff set real credentials — sharing the portal link before this
   * flips gives BrandnPack a login they cannot use. */
  has_password: boolean;
  updated_at: string;
}

/** One row of GET /partner/rates/ — the public, read-only quoting list. Only rows
 * checkout would actually offer appear here, so `price` is never null. */
export interface PublicRateZone {
  id: number;
  state: string;
  lga: string;
  lcda_name: string;
  areas_covered: string;
  dispatch_zone: string;
  price: string;
  min_days: number;
  max_days: number;
}

export interface PublicRateCard {
  partner: string;
  code: string;
  zones: PublicRateZone[];
}

/** "4000.00" → "₦4,000" (the portal never shows kobo — the rate card is whole naira). */
export function formatNaira(price: string | null): string {
  if (price === null) return "—";
  const n = Number(price);
  if (!Number.isFinite(n)) return price;
  return `₦${n.toLocaleString("en-NG", { maximumFractionDigits: 0 })}`;
}
