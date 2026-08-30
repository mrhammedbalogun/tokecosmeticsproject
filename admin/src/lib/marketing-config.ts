/** Shapes returned by the marketing admin endpoints (Plan-44). Mirrors
 * apps/marketing/admin_serializers.py.
 *
 * NOTE WHAT IS ABSENT: there is no access-token field anywhere in these types, and that
 * is not an omission. The Conversions API credentials live in the server's environment
 * (`apps/marketing/credentials.py`); the screen reports whether each is present and
 * names the variable that is missing, and never handles the value itself. */

export type ChannelCode = "meta" | "tiktok" | "snapchat" | "google_ads" | "ga4";

export interface MarketingSettingsRow {
  tracking_enabled: boolean;
  purchase_value_basis: "goods" | "grand_total";
  consent_required_countries: string[];
  consent_version: number;
}

export interface MarketingChannelRow {
  code: ChannelCode;
  label: string;
  is_enabled: boolean;
  pixel_id: string;
  secondary_id: string;
  /** Google Ads only: the server side is addressed differently from the browser tag —
   * the advertiser's 10-digit customer ID and the numeric conversion ACTION ID. */
  server_account_id: string;
  server_destination_id: string;
  browser_enabled: boolean;
  server_enabled: boolean;
  test_event_code: string;
  /** Every environment variable this channel's server-side sender needs is set. */
  credential_configured: boolean;
  /** The NAMES of the ones that are not — variable names, never values. */
  missing_settings: string[];
  /** False for Google Ads, which has no simple server-side sender: uploading
   * conversions to it means the Google Ads API (OAuth2 + an approved developer token).
   * Its `server_enabled` is ignored rather than pretending to work. */
  has_server_side: boolean;
}

export interface TestEventResult {
  ok: boolean;
  status?: number | null;
  response?: string;
  used_test_event_code?: boolean;
  /** Google only: the request was checked in full and deliberately not recorded. */
  validated_only?: boolean;
  error?: string;
  missing_settings?: string[];
}

/** What each channel's `pixel_id` field actually holds — the labels differ enough per
 * platform that one generic "Pixel ID" prompt would get two of them pasted wrong. */
export const PIXEL_ID_LABEL: Record<ChannelCode, string> = {
  meta: "Dataset (pixel) ID",
  tiktok: "Pixel code",
  snapchat: "Pixel ID",
  google_ads: "Conversion ID (AW-…)",
  ga4: "Measurement ID (G-…)",
};

export const CHANNEL_BLURB: Record<ChannelCode, string> = {
  // The single most common misunderstanding about this screen, answered where it is
  // asked: there is no Instagram row because Instagram ads run on the Meta dataset.
  meta: "Facebook AND Instagram — both run on this one dataset. There is no separate Instagram pixel.",
  tiktok: "TikTok Pixel plus the Events API.",
  snapchat: "Snap Pixel plus the Conversions API.",
  google_ads: "Browser tag plus the Data Manager API. Its two halves are addressed differently — the tag by AW-… and a label, the API by customer ID and conversion action ID.",
  ga4: "Analytics, not advertising — where the funnel is actually readable.",
};
