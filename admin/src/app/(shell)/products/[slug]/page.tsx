import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ProductEditor } from "@/components/product/ProductEditor";
import { ApiError } from "@/lib/api";
import type { ProductDetail } from "@/lib/product-form";
import {
  fetchAllPages,
  orderCategories,
  type CategoryRef,
  type CountryRef,
  type TagRef,
} from "@/lib/reference";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";
import { saveProductAction } from "./actions";

export const metadata: Metadata = { title: "Edit product" };

type Params = Promise<{ slug: string }>;

/**
 * `/products/[slug]` — the product editor, behind `products.manage`.
 *
 * FOUR FETCHES, SETTLED TOGETHER but not with `Promise.all`: the product is required and
 * the three reference lists are not. `all` rejects on the first failure, which would throw
 * away a perfectly good product because the tag list happened to error — and the tag list
 * failing should cost you the tag picker, not the page.
 *
 * A rejected promise here may be a `redirect()`, which works by throwing. `allSettled`
 * captures that rather than letting it propagate, so it is re-thrown explicitly below.
 * Without it a staff member with a merely-stale token sees an error page instead of being
 * renewed — the same trap `staff/page.tsx` documents.
 *
 * `fetchWithAuthOrBounce`, never `fetchWithAuth`: a Server Component cannot persist a
 * rotated refresh token, and the writing fetcher would blacklist the old one with nowhere
 * to put the new. The SAVE is a Server Function, which may — hence `actions.ts`.
 */
export default async function ProductEditorPage({ params }: { params: Params }) {
  const { slug } = await params;
  const path = `/products/${slug}`;
  await requireAdmin(path);

  const [productResult, categoriesResult, tagsResult, countriesResult] = await Promise.allSettled([
    fetchWithAuthOrBounce<ProductDetail>(`/admin/products/${encodeURIComponent(slug)}/`, path),
    fetchAllPages<CategoryRef>(fetchWithAuthOrBounce, "/admin/categories/", path),
    fetchAllPages<TagRef>(fetchWithAuthOrBounce, "/admin/tags/", path),
    fetchWithAuthOrBounce<CountryRef[]>("/meta/countries/", path),
  ]);

  for (const result of [productResult, categoriesResult, tagsResult, countriesResult]) {
    if (result.status === "rejected" && !(result.reason instanceof ApiError)) throw result.reason;
  }

  if (productResult.status === "rejected") {
    const error = productResult.reason as ApiError;
    if (error.status === 404) notFound();
    return (
      <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
        {error.status === 403
          ? "Your role does not include managing products."
          : "That product could not be loaded."}
      </p>
    );
  }

  const product = productResult.value;
  const categories =
    categoriesResult.status === "fulfilled" ? orderCategories(categoriesResult.value) : [];
  const tags = tagsResult.status === "fulfilled" ? tagsResult.value : [];
  // `/meta/countries/` has `pagination_class = None`, so this is a bare array. Guarded
  // anyway: a future decision to paginate it should cost the picker, not the page.
  const countries =
    countriesResult.status === "fulfilled" && Array.isArray(countriesResult.value)
      ? countriesResult.value
      : [];

  return (
    <div>
      <Link href="/products" className="text-xs text-muted underline-offset-2 hover:underline">
        ← Products
      </Link>

      <div className="mt-2 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{product.name}</h1>
          <p className="mt-1 text-sm text-muted">
            {product.variant_count} {product.variant_count === 1 ? "variant" : "variants"}
            {product.priced_currencies.length > 0 &&
              ` · priced in ${product.priced_currencies.join(", ")}`}
          </p>
        </div>
      </div>

      <div className="mt-6">
        <ProductEditor
          product={product}
          categories={categories}
          tags={tags}
          countries={countries}
          // Read here rather than in the client component: `process.env` is not available
          // in the browser bundle for a non-NEXT_PUBLIC name, and the SEO preview's URL
          // line is cosmetic enough that a wrong default would go unnoticed for months.
          siteUrl={process.env.STOREFRONT_URL ?? "https://tokecosmetics.com"}
          save={saveProductAction}
        />
      </div>
    </div>
  );
}
