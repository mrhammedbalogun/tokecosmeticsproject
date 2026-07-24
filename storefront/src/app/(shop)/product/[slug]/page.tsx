import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getProduct, type ProductDetail } from "@/lib/catalog";
import { mediaUrl } from "@/lib/media";
import { deliveryEstimateFor } from "@/lib/delivery-estimates";
import { fetchWithAuth, getAccessToken } from "@/lib/session";
import { breadcrumbJsonLd, faqJsonLd, pageMetadata, productJsonLd } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";
import { Breadcrumbs } from "@/components/plp/Breadcrumbs";
import { PdpProvider } from "@/components/product/PdpContext";
import { ProductGallery } from "@/components/product/ProductGallery";
import { BuyBox } from "@/components/product/BuyBox";
import { PdpAccordions } from "@/components/product/PdpAccordions";

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
    description: product.seo_description || product.short_description,
    path: `/product/${slug}`,
    image: mediaUrl(product.images[0]?.url ?? null),
    ogType: "product",
  });
}

/** Personalised delivery label: "Delivery to <Ikeja>: …" for logged-in users with a
 * default address; the generic country line otherwise (D5). Never throws. */
async function deliveryLineFor(country: string): Promise<string> {
  const generic = deliveryEstimateFor(country);
  if (!(await getAccessToken())) return generic;
  try {
    const addresses = await fetchWithAuth<
      { label: string; city_text: string; is_default_shipping: boolean }[]
    >("/me/addresses/", { cache: "no-store" });
    const def = addresses.find((a) => a.is_default_shipping) ?? addresses[0];
    const place = def?.city_text || def?.label;
    return place ? `${generic.replace(/^Delivery[^:]*:/, `Delivery to ${place}:`)}` : generic;
  } catch {
    return generic;
  }
}

export default async function ProductPage({ params }: { params: Params }) {
  const { slug } = await params;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
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
          <ProductGallery product={product} />
          <div>
            <BuyBox product={product} deliveryLine={deliveryLine} />
          </div>
        </div>
      </PdpProvider>
      <div className="mx-auto max-w-3xl">
        <PdpAccordions product={product} />
      </div>
      {/* Task 12 appends: ReviewList, RelatedProducts, RecentlyViewed */}
    </section>
  );
}
