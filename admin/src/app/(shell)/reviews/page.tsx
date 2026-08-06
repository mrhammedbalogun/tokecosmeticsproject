import type { Metadata } from "next";
import Link from "next/link";
import { Pagination } from "@/components/Pagination";
import { ReviewsTable } from "@/components/reviews/ReviewsTable";
import { ApiError } from "@/lib/api";
import { pageCount } from "@/lib/pagination";
import {
  parseReviewFilters,
  reviewsQueryString,
  type ReviewFilters,
  type ReviewPage,
} from "@/lib/reviews";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Reviews" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/reviews";

const TABS: { label: string; status: ReviewFilters["status"] }[] = [
  { label: "All", status: "" },
  { label: "Visible", status: "approved" },
  { label: "Hidden", status: "hidden" },
];

/**
 * `/reviews` — CUSTOMER product reviews, behind `reviews.manage`. Not the homepage's
 * curated Google reviews (`/content/reviews`, marketing.manage) — same word, different
 * feature. Reviews publish the moment a verified purchaser posts one; this screen is
 * where staff hide one from the storefront (reversible) or delete it for good.
 *
 * Same shape as `/products`: the page is not the authorization (the endpoint's
 * `HasAdminScope` is), `fetchWithAuthOrBounce` because a Server Component must never
 * refresh tokens, and filters live in the URL so a finding is shareable as a link.
 */
export default async function ReviewsPage({ searchParams }: { searchParams: SearchParams }) {
  await requireAdmin(PATH);

  const raw = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (typeof value === "string") raw.set(key, value);
    else if (Array.isArray(value) && value[0] !== undefined) raw.set(key, value[0]);
  }
  const filters = parseReviewFilters(raw);

  let page: ReviewPage | null = null;
  let error: string | null = null;
  try {
    const qs = reviewsQueryString(filters);
    page = await fetchWithAuthOrBounce<ReviewPage>(`/admin/reviews/${qs ? `?${qs}` : ""}`, PATH);
  } catch (e) {
    // `redirect()` works by THROWING; a bare catch-all would swallow the renewal bounce.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing reviews."
        : "The review list could not be loaded.";
  }

  const tabHref = (status: ReviewFilters["status"]) => {
    const qs = reviewsQueryString({ ...filters, status, page: 1 });
    return qs ? `${PATH}?${qs}` : PATH;
  };

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Reviews</h1>
      <p className="mt-1 text-sm text-muted">
        What customers say on product pages. Reviews go live as soon as they are
        written — hide one to pull it from the storefront, or delete it for good.
      </p>

      <div className="mt-6 flex flex-wrap items-center gap-2">
        {TABS.map((tab) => (
          <Link
            key={tab.label}
            href={tabHref(tab.status)}
            aria-current={filters.status === tab.status ? "page" : undefined}
            className={`rounded-full border px-3 py-1 text-sm ${
              filters.status === tab.status
                ? "border-accent bg-accent/10 font-medium"
                : "border-line hover:border-accent"
            }`}
          >
            {tab.label}
          </Link>
        ))}

        {/* A GET form: the URL is the state. `page` deliberately absent so a new
            search starts at page 1; the active tab rides along as a hidden field. */}
        <form method="get" className="ml-auto flex items-center gap-2">
          {filters.status && <input type="hidden" name="status" value={filters.status} />}
          <label htmlFor="review-search" className="sr-only">
            Search reviews
          </label>
          <input
            id="review-search"
            name="search"
            type="search"
            defaultValue={filters.search}
            placeholder="Product, customer or words in the review"
            className="w-72 rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
          />
          <button
            type="submit"
            className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
          >
            Search
          </button>
        </form>
      </div>

      <div className="mt-4">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <>
            <p className="mb-2 text-xs text-muted">
              {page?.count ?? 0} {page?.count === 1 ? "review" : "reviews"}
            </p>
            <ReviewsTable rows={page?.results ?? []} />
            <Pagination
              basePath={PATH}
              page={filters.page}
              total={pageCount(page?.count ?? 0)}
              buildQuery={(target) => reviewsQueryString({ ...filters, page: target })}
              label="Review pages"
            />
          </>
        )}
      </div>
    </div>
  );
}
