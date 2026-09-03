import type { Metadata } from "next";
import { cookies } from "next/headers";
import { ComboCard } from "@/components/combo/ComboCard";
import { Breadcrumbs } from "@/components/plp/Breadcrumbs";
import { JsonLd } from "@/components/seo/JsonLd";
import { fetchComboIndex } from "@/lib/combos";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { absoluteUrl, breadcrumbJsonLd, pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Combos",
  description:
    "Curated sets of Toke Cosmetics favourites, boxed together and priced below what the products cost on their own.",
  path: "/combo",
});

const CRUMBS = [
  { name: "Home", path: "/" },
  { name: "Combos", path: "/combo" },
];

/**
 * `/combo` — every bundle sold in the shopper's market.
 *
 * NOT PAGINATED, and that is the API's decision as much as this page's: combos are a
 * curated handful, not a catalogue, and `ComboListView` sets `pagination_class = None`.
 * A pager on a page that will hold six rows is furniture.
 *
 * The list arrives already filtered to what is buyable HERE — active, sold in this
 * market, every component still sellable and priced. A combo whose cleanser was archived
 * last night simply stops appearing, without anybody editing the combo.
 */
export default async function ComboIndexPage() {
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const combos = await fetchComboIndex(country);

  return (
    <section className="mx-auto max-w-7xl px-4 py-8">
      <JsonLd data={breadcrumbJsonLd(CRUMBS)} />
      {combos.length > 0 && (
        <JsonLd
          data={{
            "@context": "https://schema.org",
            "@type": "ItemList",
            name: "Toke Cosmetics combos",
            itemListElement: combos.map((combo, i) => ({
              "@type": "ListItem",
              position: i + 1,
              name: combo.name,
              url: absoluteUrl(`/combo/${combo.slug}`),
            })),
          }}
        />
      )}
      <Breadcrumbs crumbs={CRUMBS} />

      <header className="mt-6 max-w-2xl">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
          Buy the set, keep the change
        </p>
        <h1 className="mt-2 font-display text-3xl leading-tight sm:text-4xl">Combos</h1>
        <p className="mt-3 text-muted">
          Routines we put together ourselves — the products that work best beside each
          other, boxed as one and priced below what they cost separately. Everything
          inside is the same full-size product you would buy on its own.
        </p>
      </header>

      {combos.length === 0 ? (
        <p className="mt-10 rounded-[var(--radius-card)] border border-dashed border-line bg-surface p-10 text-center text-muted">
          No combos are running right now. Check back soon.
        </p>
      ) : (
        <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {combos.map((combo, i) => (
            <ComboCard key={combo.slug} combo={combo} priority={i < 3} />
          ))}
        </div>
      )}
    </section>
  );
}
