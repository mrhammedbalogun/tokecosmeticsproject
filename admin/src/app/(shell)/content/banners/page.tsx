import type { Metadata } from "next";
import Link from "next/link";
import { BannerManager } from "@/components/content/BannerManager";
import { ApiError } from "@/lib/api";
import type { BannerRow } from "@/lib/banners";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Banners" };

const PATH = "/content/banners";

/** `/content/banners` — behind `marketing.manage`, not `cms.manage`: a banner announces a
 *  promotion, so a copywriter should not be able to override a live campaign's placement. */
export default async function BannersPage() {
  await requireAdmin(PATH);

  let banners: BannerRow[] = [];
  let error: string | null = null;
  try {
    const data = await fetchWithAuthOrBounce<{ results: BannerRow[] } | BannerRow[]>(
      "/admin/banners/",
      PATH,
    );
    banners = Array.isArray(data) ? data : (data?.results ?? []);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include running campaigns."
        : "The banners could not be loaded.";
  }

  return (
    <div>
      <div>
        <Link href="/content" className="text-sm text-muted hover:text-fg">
          ← Content
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">Banners</h1>
        <p className="mt-1 text-sm text-muted">
          Announcement strips and the homepage hero. Scheduling is applied on the server,
          so a banner never appears early.
        </p>
      </div>
      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <BannerManager banners={banners} />
        )}
      </div>
    </div>
  );
}
