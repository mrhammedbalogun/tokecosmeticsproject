import type { Metadata } from "next";
import { FaqEditor } from "@/components/content/FaqEditor";
import { ApiError } from "@/lib/api";
import { groupByCategory, publicSummary, type FaqCategoryRow, type FaqItemRow } from "@/lib/faq";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "FAQ" };

const PATH = "/content/faq";

/** `/content/faq` — the questions on the shop's `/faq` page, behind `cms.manage`.
 *
 * Same scope as pages: an answer about refunds is as load-bearing as a policy page and
 * is written by the same person. */
export default async function FaqAdminPage() {
  await requireAdmin(PATH);

  let categories: FaqCategoryRow[] = [];
  let items: FaqItemRow[] = [];
  let error: string | null = null;
  try {
    // `page_size` is set high deliberately: the editor reorders and publishes across the
    // whole FAQ at once, and a paginated second screen would make "what does the shop
    // show right now" unanswerable without clicking through.
    const [cats, rows] = await Promise.all([
      fetchWithAuthOrBounce<{ results: FaqCategoryRow[] } | FaqCategoryRow[]>(
        "/admin/faq-categories/?page_size=100", PATH),
      fetchWithAuthOrBounce<{ results: FaqItemRow[] } | FaqItemRow[]>(
        "/admin/faq-items/?page_size=500", PATH),
    ]);
    categories = Array.isArray(cats) ? cats : (cats?.results ?? []);
    items = Array.isArray(rows) ? rows : (rows?.results ?? []);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error = e.status === 403
      ? "Your role does not include managing content."
      : "The FAQ could not be loaded.";
  }

  const groups = groupByCategory(categories, items);
  const summary = publicSummary(groups);

  return (
    <div>
      <div>
        <h1 className="text-lg font-semibold tracking-tight">FAQ</h1>
        <p className="mt-1 text-sm text-muted">
          The questions on <span className="font-medium">tokecosmetics.com/faq</span>.
          A category with nothing published in it does not appear on the shop at all.
        </p>
      </div>

      {!error && (
        <p className="mt-4 rounded-[var(--radius-card)] border border-line bg-surface p-3 text-sm">
          <span className="font-medium">{summary.liveQuestions}</span> question
          {summary.liveQuestions === 1 ? "" : "s"} live across{" "}
          <span className="font-medium">{summary.liveCategories}</span> categor
          {summary.liveCategories === 1 ? "y" : "ies"}
          {summary.awaiting > 0 && (
            <>
              {" · "}
              <span className="text-warn">
                {summary.awaiting} awaiting an answer
              </span>
            </>
          )}
        </p>
      )}

      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <FaqEditor groups={groups} />
        )}
      </div>
    </div>
  );
}
