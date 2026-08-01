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
import {
  deleteImageAction,
  updateImageAction,
  uploadImageAction,
  type ProductImage,
} from "./image-actions";
import { savePriceAction } from "./price-actions";
import { createVariantAction, updateVariantAction } from "./variant-actions";
import { adjustStockAction } from "./stock-actions";
import type { PriceRow, VariantRow } from "@/lib/product-prices";
import type { StockRow } from "@/lib/product-stock";

/** The configured currencies, as on the products list. There is still no endpoint listing
 *  configured currencies; `core/migrations/0003_seed_countries_currencies.py` is the
 *  source. */
const CURRENCIES = ["NGN", "GBP", "USD", "CAD"] as const;

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

  // Images are a SEPARATE fetch because `ProductAdminSerializer` does not nest them — only
  // the list's single `thumbnail`. Filtered by product, which is possible because Task 1
  // gave `ProductImageAdminViewSet` a `product` filter; unfiltered it would return every
  // image in the catalogue and serialise them all into this page's RSC payload.
  //
  // Fetched AFTER the product, deliberately: it needs the product's id, and a 404 on the
  // product should not be preceded by a pointless image request.
  //
  // FOUR PRODUCT-SCOPED LISTS, all filtered server-side. Unfiltered, `/admin/variants/`
  // returns all 122 in production and `/admin/prices/` all 121 — and every one would be
  // serialised into this page's RSC payload whether rendered or not.
  //
  // Each failure costs ONE TAB, never the page: the editor holds unsaved-able text in
  // Details, Content and SEO, and a dead price endpoint must not take that with it.
  const [imagesResult, variantsResult, stockResult, pricesResult] = await Promise.allSettled([
    fetchWithAuthOrBounce<{ results: ProductImage[] }>(
      `/admin/images/?product=${product.id}`,
      path,
    ),
    fetchAllPages<VariantRow>(
      fetchWithAuthOrBounce,
      `/admin/variants/?product=${product.id}`,
      path,
    ),
    fetchAllPages<StockRow>(
      fetchWithAuthOrBounce,
      `/admin/stock/?variant__product=${product.id}`,
      path,
    ),
    fetchAllPages<PriceRow>(
      fetchWithAuthOrBounce,
      `/admin/prices/?variant__product=${product.id}`,
      path,
    ),
  ]);

  for (const result of [imagesResult, variantsResult, stockResult, pricesResult]) {
    if (result.status === "rejected" && !(result.reason instanceof ApiError)) throw result.reason;
  }

  const images = imagesResult.status === "fulfilled" ? (imagesResult.value.results ?? []) : [];
  // `fetchAllPages` for these three, not a single request: DRF pages at 24, and a product
  // with more variants or a fuller price matrix than today's would otherwise be silently
  // truncated — the same trap the category picker had.
  const variants = variantsResult.status === "fulfilled" ? variantsResult.value : [];
  const stock = stockResult.status === "fulfilled" ? stockResult.value : [];
  const prices = pricesResult.status === "fulfilled" ? pricesResult.value : [];

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
          initialImages={images}
          imageActions={{
            upload: uploadImageAction,
            update: updateImageAction,
            remove: deleteImageAction,
          }}
          variants={variants}
          createVariant={createVariantAction}
          updateVariant={updateVariantAction}
          stock={stock}
          initialPrices={prices}
          currencies={CURRENCIES}
          savePrice={savePriceAction}
          adjustStock={adjustStockAction}
          save={saveProductAction}
        />
      </div>
    </div>
  );
}
