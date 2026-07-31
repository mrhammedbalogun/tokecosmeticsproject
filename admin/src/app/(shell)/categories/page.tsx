import type { Metadata } from "next";
import { CategoryManager } from "@/components/CategoryManager";
import { ApiError } from "@/lib/api";
import { countsByCategory, orderCategories, type CategoryRef } from "@/lib/category-tree";
import { fetchAllPages } from "@/lib/reference";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";
import { saveCategoryAction } from "./actions";

export const metadata: Metadata = { title: "Categories" };

const PATH = "/categories";

/**
 * `/categories` — the tree, and a form to edit one.
 *
 * BOTH LISTS ARE PAGE-FOLLOWED. Production holds 40 categories against DRF's `PAGE_SIZE`
 * of 24, so a single request would show 24 of them and silently omit the rest — which
 * presents as "that category does not exist" rather than as a bug.
 *
 * THE PRODUCT COUNTS ARE DERIVED CLIENT-SIDE from the products list rather than asked for,
 * because no endpoint reports them. That is affordable at 69 products and would not be at
 * 6,900; when it stops being affordable the answer is an annotated count on the category
 * serializer, not a bigger fetch here. The counts are a convenience — a failed product
 * fetch costs the counts, never the tree.
 */
export default async function CategoriesPage() {
  await requireAdmin(PATH);

  const [categoriesResult, productsResult] = await Promise.allSettled([
    fetchAllPages<CategoryRef>(fetchWithAuthOrBounce, "/admin/categories/", PATH),
    fetchAllPages<{ categories: number[] }>(fetchWithAuthOrBounce, "/admin/products/", PATH),
  ]);

  for (const result of [categoriesResult, productsResult]) {
    // `redirect()` throws; re-thrown so a merely-stale session is renewed rather than
    // shown an error page.
    if (result.status === "rejected" && !(result.reason instanceof ApiError)) throw result.reason;
  }

  if (categoriesResult.status === "rejected") {
    const error = categoriesResult.reason as ApiError;
    return (
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Categories</h1>
        <p className="mt-6 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
          {error.status === 403
            ? "Your role does not include managing products."
            : "The categories could not be loaded."}
        </p>
      </div>
    );
  }

  const categories = orderCategories(categoriesResult.value);
  const counts = Object.fromEntries(
    countsByCategory(productsResult.status === "fulfilled" ? productsResult.value : []),
  );

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Categories</h1>
      <p className="mt-1 text-sm text-muted">
        {categories.length} categories. Pick one to rename it, move it, or hide it from the
        storefront.
      </p>

      <div className="mt-6">
        <CategoryManager categories={categories} counts={counts} action={saveCategoryAction} />
      </div>
    </div>
  );
}
