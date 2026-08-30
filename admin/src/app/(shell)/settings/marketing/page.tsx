import type { Metadata } from "next";
import Link from "next/link";
import { MarketingSettings } from "@/components/config/MarketingSettings";
import { ApiError } from "@/lib/api";
import type { MarketingChannelRow, MarketingSettingsRow } from "@/lib/marketing-config";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Advert tracking" };

const PATH = "/settings/marketing";

export default async function MarketingSettingsPage() {
  await requireAdmin(PATH);

  let settings: MarketingSettingsRow | null = null;
  let channels: MarketingChannelRow[] = [];
  let error: string | null = null;
  try {
    [settings, channels] = await Promise.all([
      fetchWithAuthOrBounce<MarketingSettingsRow>("/admin/marketing/settings/", PATH),
      // The list request is also what SEEDS a row for every platform the code can serve
      // (`ensure_channel_rows`), so a newly added channel appears here with no migration.
      fetchWithAuthOrBounce<MarketingChannelRow[]>("/admin/marketing/channels/", PATH),
    ]);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing advert tracking."
        : "The marketing settings could not be loaded.";
  }

  return (
    <div>
      <Link href="/settings" className="text-sm text-muted hover:text-foreground">
        ← Settings
      </Link>
      <h1 className="mt-2 text-lg font-semibold tracking-tight">Advert tracking</h1>
      <p className="mt-1 max-w-3xl text-sm text-muted">
        The pixels and conversion APIs that tell Facebook, Instagram, TikTok, Snapchat and
        Google which adverts produced sales. Facebook and Instagram share one Meta
        dataset — there is no separate Instagram pixel.
      </p>

      <div className="mt-6">
        {error || !settings ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error ?? "The marketing settings could not be loaded."}
          </p>
        ) : (
          <MarketingSettings settings={settings} channels={channels} />
        )}
      </div>
    </div>
  );
}
