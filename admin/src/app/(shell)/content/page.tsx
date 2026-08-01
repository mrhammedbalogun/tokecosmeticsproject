import type { Metadata } from "next";
import { PagesList } from "@/components/content/PagesList";
import { ApiError } from "@/lib/api";
import type { PageRow } from "@/lib/pages";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Content" };

const PATH = "/content";

/**
 * `/content` — CMS pages, behind `cms.manage`.
 *
 * THIS IS THE FIRST THING THE `Content` ROLE CAN DO. Plan-16 seeded the scope and the nav
 * link; until Plan-19a nothing declared it, so that role could sign in and reach a 404.
 */
export default async function ContentPage() {
  await requireAdmin(PATH);

  let pages: PageRow[] = [];
  let error: string | null = null;
  try {
    const data = await fetchWithAuthOrBounce<{ results: PageRow[] } | PageRow[]>(
      "/admin/pages/",
      PATH,
    );
    pages = Array.isArray(data) ? data : (data?.results ?? []);
  } catch (e) {
    // `redirect()` throws; rethrown so a merely-stale session is renewed.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing content."
        : "The pages could not be loaded.";
  }

  return (
    <div>
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Content</h1>
        <p className="mt-1 text-sm text-muted">
          Standalone pages — policies, contact, FAQs. Each one is a URL on the shop.
        </p>
      </div>
      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <PagesList pages={pages} />
        )}
      </div>
    </div>
  );
}
