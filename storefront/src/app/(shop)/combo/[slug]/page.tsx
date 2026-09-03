import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { ComboBuyBox } from "@/components/combo/ComboBuyBox";
import { ComboContents } from "@/components/combo/ComboContents";
import { Breadcrumbs } from "@/components/plp/Breadcrumbs";
import { JsonLd } from "@/components/seo/JsonLd";
import { ApiError } from "@/lib/api";
import { getCombo, type ComboDetail } from "@/lib/combos";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY, formatMoney } from "@/lib/country";
import { deliveryEstimateFor } from "@/lib/delivery-estimates";
import { mediaUrl } from "@/lib/media";
import { breadcrumbJsonLd, comboJsonLd, pageMetadata, stripHtml } from "@/lib/seo";

type Params = Promise<{ slug: string }>;

async function loadCombo(slug: string, country: string): Promise<ComboDetail | null> {
  try {
    return await getCombo(slug, country);
  } catch (e) {
    // A combo withdrawn from this market answers 404 rather than serving a stub page,
    // which would be indexed as one. Anything else is a real fault and bubbles.
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug } = await params;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const combo = await loadCombo(slug, country);
  if (!combo) return { title: "Combo not found" };
  return pageMetadata({
    title: combo.seo_title || combo.name,
    // short_description is rich HTML; a meta description must be plain text.
    description:
      combo.seo_description ||
      stripHtml(combo.short_description) ||
      stripHtml(combo.description),
    path: `/combo/${slug}`,
    image: mediaUrl(combo.image ?? combo.items[0]?.image ?? null),
    ogType: "product",
  });
}

/**
 * `/combo/{slug}` — one bundle.
 *
 * ── WHAT THE PAGE HAS TO ANSWER, IN ORDER ───────────────────────────────────────────
 *
 * 1. What is this, and what does it save? — the hero and the buy panel, side by side, so
 *    the price and the strike-through are visible without scrolling.
 * 2. What exactly is in the box? — full cards, with the CHOSEN size and option named,
 *    each linking to its own product page so the "bought separately" figure is checkable.
 * 3. Why these things together? — the curator's description, in their own words.
 *
 * The order is deliberate and is the reason the contents are not an accordion: on a
 * product page the ingredients can be folded away because the shopper already knows what
 * they are buying. On a bundle page, what is inside IS the product.
 */
export default async function ComboPage({ params }: { params: Params }) {
  const { slug } = await params;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const combo = await loadCombo(slug, country);
  if (!combo) notFound();

  const hero = mediaUrl(combo.image);
  const pricing = combo.pricing;
  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Combos", path: "/combo" },
    { name: combo.name, path: `/combo/${slug}` },
  ];
  const unitCount = combo.items.reduce((n, item) => n + item.quantity, 0);

  return (
    <section className="mx-auto max-w-7xl px-4 py-8">
      {/* Next 16's typed Metadata OpenGraph has no `product` type (see lib/seo.ts);
          emit the correct property-based OG tag here — React 19 hoists it to <head>. */}
      <meta property="og:type" content="product" />
      <JsonLd data={comboJsonLd(combo, `/combo/${slug}`)} />
      <JsonLd data={breadcrumbJsonLd(crumbs)} />
      <Breadcrumbs crumbs={crumbs} />

      <div className="mt-6 grid gap-10 lg:grid-cols-[1.15fr_1fr]">
        <div>
          <div className="relative aspect-[4/3] overflow-hidden rounded-[var(--radius-card)] bg-beige">
            {hero ? (
              <Image
                src={hero}
                alt={combo.name}
                fill
                priority
                sizes="(max-width: 1024px) 100vw, 55vw"
                className="object-cover"
              />
            ) : (
              // No hero: the contents ARE the artwork. An empty frame on the one page
              // whose whole job is to show what is in the box would be the worst of both.
              <div className="flex h-full flex-wrap items-center justify-center gap-4 p-8">
                {combo.items.slice(0, 4).map((item) => {
                  const img = mediaUrl(item.image);
                  return img ? (
                    <span
                      key={item.sku}
                      className="relative h-32 w-32 overflow-hidden rounded-full border-4 border-surface shadow-sm"
                    >
                      <Image src={img} alt="" fill sizes="128px" className="object-cover" />
                    </span>
                  ) : null;
                })}
              </div>
            )}
          </div>

          {hero && combo.items.length > 0 && (
            <ul className="mt-3 flex gap-3 overflow-x-auto pb-1">
              {combo.items.map((item) => {
                const img = mediaUrl(item.image);
                return (
                  <li key={item.sku} className="shrink-0">
                    <span className="relative block h-20 w-20 overflow-hidden rounded-lg border border-line bg-beige">
                      {img && (
                        <Image src={img} alt={item.product_name} fill sizes="80px" className="object-cover" />
                      )}
                      {item.quantity > 1 && (
                        <span className="absolute right-1 top-1 rounded-full bg-foreground/85 px-1.5 text-[10px] font-semibold text-white">
                          ×{item.quantity}
                        </span>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
            Combo · {unitCount} {unitCount === 1 ? "product" : "products"}
          </p>
          <h1 className="mt-2 font-display text-3xl leading-tight sm:text-4xl">
            {combo.name}
          </h1>
          {combo.short_description && (
            <div
              className="rich-text mt-3 text-muted"
              // nh3-sanitised on write (apps/cms/sanitize.py) — the same content the
              // admin's rich-text editor produced.
              dangerouslySetInnerHTML={{ __html: combo.short_description }}
            />
          )}

          <div className="mt-5">
            <ComboBuyBox combo={combo} deliveryLine={deliveryEstimateFor(country)} />
          </div>

          {pricing && (
            <ol className="mt-4 space-y-1 text-sm text-muted">
              {combo.items.map((item) => (
                <li key={item.sku} className="flex justify-between gap-4">
                  <span className="truncate">
                    {item.quantity > 1 && (
                      <span className="text-foreground">{item.quantity} × </span>
                    )}
                    {item.product_name}
                    {/* The chosen option, so two sizes of one product are two readable
                        rows rather than the same name twice at different prices. */}
                    {Object.values(item.option_values ?? {}).filter(Boolean).length > 0 && (
                      <span className="text-xs">
                        {" "}
                        ({Object.values(item.option_values).filter(Boolean).join(", ")})
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 tabular-nums">
                    {item.line_total ? formatMoney(item.line_total, pricing.currency) : "—"}
                  </span>
                </li>
              ))}
              <li className="flex justify-between gap-4 border-t border-line pt-1 font-medium text-foreground">
                <span>Bought separately</span>
                <span className="tabular-nums">
                  <s>{formatMoney(pricing.components_total, pricing.currency)}</s>
                </span>
              </li>
              <li className="flex justify-between gap-4 font-medium text-accent">
                <span>Combo price</span>
                <span className="tabular-nums">
                  {formatMoney(pricing.amount, pricing.currency)}
                </span>
              </li>
            </ol>
          )}
        </div>
      </div>

      <div className="mt-14 border-t border-line pt-8">
        <h2 className="font-display text-2xl">What&rsquo;s in the box</h2>
        <p className="mt-1 text-sm text-muted">
          Full-size products, in the exact size and option shown. Tap any of them to read
          the full page.
        </p>
        <div className="mt-6">
          <ComboContents items={combo.items} currency={pricing?.currency ?? "NGN"} />
        </div>
      </div>

      {combo.description && (
        <div className="mt-14 border-t border-line pt-8">
          <h2 className="font-display text-2xl">Why these go together</h2>
          <div
            className="rich-text mt-4 max-w-3xl text-[15px] leading-relaxed"
            // nh3-sanitised on write, rendered with the site-wide `.rich-text` rules.
            dangerouslySetInnerHTML={{ __html: combo.description }}
          />
        </div>
      )}

      <div className="mt-14 border-t border-line pt-8">
        <Link
          href="/combo"
          className="text-sm font-medium text-accent underline-offset-4 hover:underline"
        >
          ← See every combo
        </Link>
      </div>
    </section>
  );
}
