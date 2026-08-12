import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { apiFetch, ApiError } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getProduct, type ProductDetail } from "@/lib/catalog";
import { mediaUrl } from "@/lib/media";
import { deliveryEstimateFor } from "@/lib/delivery-estimates";
import { getAccessToken } from "@/lib/session";
import { REFRESH_COOKIE } from "@/lib/auth";
import { breadcrumbJsonLd, faqJsonLd, pageMetadata, productJsonLd, stripHtml } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";
import { Breadcrumbs } from "@/components/plp/Breadcrumbs";
import { PdpProvider } from "@/components/product/PdpContext";
import { ProductGallery } from "@/components/product/ProductGallery";
import { ProductVideos } from "@/components/product/ProductVideos";
import { BuyBox } from "@/components/product/BuyBox";
import { PdpAccordions } from "@/components/product/PdpAccordions";
import { ReviewList } from "@/components/product/ReviewList";
import { RelatedProducts } from "@/components/product/RelatedProducts";
import { RecentlyViewed } from "@/components/product/RecentlyViewed";
import { RecentlyViewedTracker } from "@/components/product/RecentlyViewedTracker";

type Params = Promise<{ slug: string }>;

async function loadProduct(slug: string, country: string): Promise<ProductDetail | null> {
  try {
    return await getProduct(slug, country);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug } = await params;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const product = await loadProduct(slug, country);
  if (!product) return { title: "Product not found" };
  return pageMetadata({
    title: product.seo_title || product.name,
    // short_description is rich HTML; a meta description must be plain text.
    description: product.seo_description || stripHtml(product.short_description),
    path: `/product/${slug}`,
    image: mediaUrl(product.images[0]?.url ?? null),
    ogType: "product",
  });
}

/** Personalised delivery label: "Delivery to <Ikeja>: …" for logged-in users with a
 * default address; the generic country line otherwise (D5). Never throws.
 *
 * Deliberately `apiFetch` with the token read by hand, NOT a refreshing fetcher. Two
 * reasons, and both matter:
 *
 * 1. This is a Server Component, so a token rotation could not be persisted — and
 *    SimpleJWT blacklists the old refresh token on use, so "refresh, fail to save"
 *    silently ends a 14-day session. The `catch` below would have hidden it completely.
 *    The session renews instead at the next Route Handler call or gated navigation.
 * 2. A PUBLIC product page must never bounce a shopper to login over a cosmetic delivery
 *    label. An expired token here just means the generic line.
 */
async function deliveryLineFor(country: string): Promise<string> {
  const generic = deliveryEstimateFor(country);
  const token = await getAccessToken();
  if (!token) return generic;
  try {
    const addresses = await apiFetch<
      { label: string; city_text: string; is_default_shipping: boolean }[]
    >("/me/addresses/", { token, country, cache: "no-store" });
    const def = addresses.find((a) => a.is_default_shipping) ?? addresses[0];
    const place = def?.city_text || def?.label;
    return place ? `${generic.replace(/^Delivery[^:]*:/, `Delivery to ${place}:`)}` : generic;
  } catch {
    return generic;
  }
}

export default async function ProductPage({ params }: { params: Params }) {
  const { slug } = await params;
  const jar = await cookies();
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  // Gate on the refresh cookie, not access (14-min lifetime) — same reasoning as
  // src/proxy.ts. A hint only: the review form's eligibility probe tells the truth.
  const signedIn = Boolean(jar.get(REFRESH_COOKIE)?.value);
  const product = await loadProduct(slug, country);
  if (!product) notFound();
  const deliveryLine = await deliveryLineFor(country);

  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Shop", path: "/products" },
    { name: product.name, path: `/product/${slug}` },
  ];

  return (
    <section className="mx-auto max-w-7xl px-4 py-8">
      {/* Next 16's typed Metadata OpenGraph has no `product` type (see lib/seo.ts);
          emit the correct property-based OG tag here — React 19 hoists it to <head>. */}
      <meta property="og:type" content="product" />
      <JsonLd data={productJsonLd(product, `/product/${slug}`)} />
      <JsonLd data={breadcrumbJsonLd(crumbs)} />
      {product.faqs.length > 0 && <JsonLd data={faqJsonLd(product.faqs)} />}
      <Breadcrumbs crumbs={crumbs} />
      <PdpProvider variants={product.variants}>
        <div className="mt-6 grid gap-10 lg:grid-cols-2">
          <div>
            <ProductGallery product={product} />
            <ProductVideos product={product} />
          </div>
          <div>
            <BuyBox product={product} deliveryLine={deliveryLine} />
          </div>
        </div>
      </PdpProvider>
      <div className="mx-auto max-w-3xl">
        <PdpAccordions product={product} />
      </div>
      <RecentlyViewedTracker entry={{
        slug, name: product.name,
        image: mediaUrl(product.images[0]?.url ?? null),
        from_price: product.variants.find((v) => v.price)?.price?.amount ?? null,
        currency: product.variants.find((v) => v.price)?.price?.currency ?? "NGN",
      }} />
      <ReviewList slug={slug} ratingAvg={product.rating_avg} ratingCount={product.rating_count} signedIn={signedIn} />
      <RelatedProducts products={product.related} />
      <RecentlyViewed excludeSlug={slug} />
    </section>
  );
}
