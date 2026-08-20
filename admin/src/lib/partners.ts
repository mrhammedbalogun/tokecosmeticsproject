/** Shared row types for the delivery-partner feature (Plan-39): the partner portal
 * (`/partner`) and the staff oversight page (`/settings/partners`) render the same
 * backend rows, so the shapes live once, here. */

export interface PartnerZoneRow {
  id: number;
  lga_region: number;
  lga_name: string;
  lcda_name: string;
  areas_covered: string;
  dispatch_zone: string;
  /** null = "the partner has not set a price yet" — the row never reaches checkout. */
  price: string | null;
  is_active: boolean;
  updated_at: string;
}

/** The staff serializer additionally names the partner on each zone row. */
export interface AdminPartnerZoneRow extends PartnerZoneRow {
  partner: number;
  partner_name: string;
}

export interface PartnerLgaOption {
  id: number;
  name: string;
}

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

/** "4000.00" → "₦4,000" (the portal never shows kobo — the rate card is whole naira). */
export function formatNaira(price: string | null): string {
  if (price === null) return "—";
  const n = Number(price);
  if (!Number.isFinite(n)) return price;
  return `₦${n.toLocaleString("en-NG", { maximumFractionDigits: 0 })}`;
}
