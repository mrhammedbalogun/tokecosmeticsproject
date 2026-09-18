/**
 * The tracking configuration the storefront renders its tags from (Plan-44).
 *
 * ONE cached fetch, shared by the consent banner and the pixel loader. Cached rather
 * than dynamic on purpose: reading it through `cookies()` or `headers()` would opt every
 * page in the shop out of static rendering, which is a real cost for a catalogue that
 * lives on ISR — and a pixel id changes about once a year.
 *
 * Everything here is public. The backend's serialiser refuses to publish a credential or
 * a test event code; see `apps/marketing/serializers.py`.
 */
import { apiFetch } from "@/lib/api";

export type ChannelCode = "meta" | "tiktok" | "snapchat" | "google_ads" | "ga4";

export interface MarketingChannelConfig {
  code: ChannelCode;
  pixel_id: string;
  /** Google Ads only: the conversion LABEL, the second half of `AW-123/AbC-D_efG`. */
  secondary_id: string;
}

export interface MarketingConfig {
  tracking_enabled: boolean;
  consent_version: number;
  consent_required_countries: string[];
  channels: MarketingChannelConfig[];
}

/** What the storefront assumes when the API cannot be reached.
 *
 * NOTHING LOADS. A tracking layer that fails open would start pixels with no consent
 * policy behind them, in whichever country the visitor happens to be — which is the one
 * failure mode this whole plan exists to avoid. Losing a day of ad measurement to an API
 * outage is the cheaper mistake, and it is recoverable.
 */
export const NO_TRACKING: MarketingConfig = {
  tracking_enabled: false,
  consent_version: 0,
  consent_required_countries: [],
  channels: [],
};

/** The tag Django flushes on a Marketing-screen write (`apps/marketing/revalidate.py`).
 *
 * The TTL alone was never the right guarantee for this payload. `tracking_enabled` is a
 * kill switch, `consent_required_countries` is a legal position, and a pixel id decides
 * which ad account receives the shop's customer data — each is turned off or corrected
 * BECAUSE something is wrong, which is the one moment "within five minutes" is not an
 * answer. With the tag in place the switch bites on save, and the hour below is only the
 * floor under an unreachable backend rather than the mechanism.
 *
 * An HOUR, up from 300s, precisely BECAUSE the tag carries the urgency now. A pixel id
 * changes about once a year; polling for it twelve times an hour was buying nothing the
 * flush does not already deliver instantly. */
export async function getMarketingConfig(): Promise<MarketingConfig> {
  try {
    return await apiFetch<MarketingConfig>("/marketing/config/", {
      next: { revalidate: 3600, tags: ["marketing"] },
    });
  } catch {
    return NO_TRACKING;
  }
}
