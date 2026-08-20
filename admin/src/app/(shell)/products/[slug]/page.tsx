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
import { getAdminMeOrNull } from "@/lib/admin-me";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";
import { DeleteProductButton } from "@/components/product/DeleteProductButton";
import { deleteProductAction, saveProductAction } from "./actions";
import {
  deleteImageAction,
  updateImageAction,
  uploadImageAction,
  type ProductImage,
} from "./image-actions";
import { savePriceAction } from "./price-actions";
import {
  attachVideoAction,
  deleteVideoAction,
  updateVideoAction,
  type ProductVideo,
} from "./video-actions";
import {
  finalizeVideoAction,
  requestVideoTicketAction,
} from "@/app/(shell)/content/media/actions";
import {
  createVariantAction,
  deleteVariantAction,
  updateVariantAction,
} from "./variant-actions";
import { adjustStockAction } from "./stock-actions";
import type { PriceRow, VariantRow } from "@/lib/product-prices";
import type { StockRow } from "@/lib/product-stock";

/** The configured currencies, as on the products list. There is still no endpoint listing
 *  configured currencies; `core/migrations/0003_seed_countries_currencies.py` is the
 *  source. */
const CURRENCIES = ["NGN", "GBP", "USD", "CAD"] as const;

/** The concrete wait from DRF's throttle detail ("… Expected available in 58 seconds."),
 *  or the honest vague version when the shape ever changes. */
function throttleWait(error: ApiError): string {
  const detail = (error.data as { detail?: unknown } | null)?.detail;
  const seconds = typeof detail === "string" ? /in (\d+) second/.exec(detail)?.[1] : undefined;
  return seconds ? `Wait ${seconds} seconds` : "Wait a minute";
}

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
          : error.status === 429
            ? // Named honestly, because this replaced the whole editor mid-session on
              // 2026-08-10 and read as a crash. The product is fine; the API is
              // metering. DRF's detail carries the actual wait, so prefer it.
              `The server is rate-limiting this session. ${throttleWait(error)}, then refresh — nothing was lost on the server.`
            : "That product could not be loaded."}
      </p>
    );
  }

  const product = productResult.value;

  // Whether to OFFER the delete control. Same pattern as the order page's scope
  // passing: read server-side, and never the gate — `ProductAdminViewSet.destroy`
  // re-checks products.delete on the request itself. `getAdminMeOrNull` failing
  // (null) simply hides the button, which fails in the safe direction.
  const me = await getAdminMeOrNull();
  const canDelete = me?.scopes.includes("products.delete") ?? false;
  // Variant delete was widened from products.delete to the products.manage floor on
  // 2026-08-20 (Hammed's call): pruning a variant is catalogue day-work. Still read
  // from the scopes rather than hardcoded true, so the offer stays honest if the
  // grant table ever changes; the API re-checks regardless.
  const canDeleteVariants = me?.scopes.includes("products.manage") ?? false;

  // Images are a SEPARATE fetch because `ProductAdminSerializer` does not nest them — only
  // the list's single `thumbnail`. Filtered by product, which is possible because Task 1
  // gave `ProductImageAdminViewSet` a `product` filter; unfiltered it would return every
  // image in the catalogue and serialise them all into this page's RSC payload.
  //
  // Fetched AFTER the product, deliberately: it needs the product's id, and a 404 on the
  // product should not be preceded by a pointless image request.
  //
  // FIVE PRODUCT-SCOPED LISTS, all filtered server-side. Unfiltered, `/admin/variants/`
  // returns all 122 in production and `/admin/prices/` all 121 — and every one would be
  // serialised into this page's RSC payload whether rendered or not.
  //
  // Each failure costs ONE TAB, never the page: the editor holds unsaved-able text in
  // Details, Content and SEO, and a dead price endpoint must not take that with it.
  const [imagesResult, variantsResult, stockResult, pricesResult, videosResult] = await Promise.allSettled([
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
    fetchWithAuthOrBounce<{ results: ProductVideo[] }>(
      `/admin/videos/?product=${product.id}`,
      path,
    ),
  ]);

  for (const result of [imagesResult, variantsResult, stockResult, pricesResult, videosResult]) {
    if (result.status === "rejected" && !(result.reason instanceof ApiError)) throw result.reason;
  }

  // A THROTTLED SECONDARY FETCH MUST SAY SO. The catch-to-empty below is right for a
  // genuinely broken endpoint ("each failure costs one tab, never the page") — but a
  // 429'd variants or prices fetch rendered a real product with apparently ZERO
  // variants and prices, which reads as data loss and invites someone to recreate
  // them. Same incident as the product-fetch 429 above, worse costume.
  const throttled = [imagesResult, variantsResult, stockResult, pricesResult, videosResult].some(
    (result) => result.status === "rejected" && (result.reason as ApiError).status === 429,
  );

  const images = imagesResult.status === "fulfilled" ? (imagesResult.value.results ?? []) : [];
  const videos = videosResult.status === "fulfilled" ? (videosResult.value.results ?? []) : [];
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
        {canDelete && (
          <DeleteProductButton
            slug={product.slug}
            name={product.name}
            onDelete={deleteProductAction}
          />
        )}
      </div>

      {throttled && (
        <p className="mt-4 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-3 text-sm text-warn">
          The server is rate-limiting this session, so parts of this page (variants,
          prices, stock, images or videos) may look empty when they are not. Nothing is lost —
          wait a minute, then refresh before editing.
        </p>
      )}

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
          initialVideos={videos}
          videoActions={{
            // The upload half is the MEDIA LIBRARY's pair (`marketing.manage`) — the
            // rbac.py comment on that scope explains why product staff can call it.
            ticket: requestVideoTicketAction,
            finalize: finalizeVideoAction,
            attach: attachVideoAction,
            update: updateVideoAction,
            remove: deleteVideoAction,
          }}
          variants={variants}
          createVariant={createVariantAction}
          updateVariant={updateVariantAction}
          deleteVariant={deleteVariantAction}
          canDeleteVariants={canDeleteVariants}
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
