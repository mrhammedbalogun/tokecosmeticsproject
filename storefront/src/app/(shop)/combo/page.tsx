import type { Metadata } from "next";
import { cookies } from "next/headers";
import { ComboCard } from "@/components/combo/ComboCard";
import { Breadcrumbs } from "@/components/plp/Breadcrumbs";
import { JsonLd } from "@/components/seo/JsonLd";
import { comboGift, comboSavingPercent, fetchComboIndex } from "@/lib/combos";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { absoluteUrl, breadcrumbJsonLd, pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Combo Deals",
  // Deliberately makes NO claim about the reward. This is a static export, written
  // before the list is fetched, so it cannot know whether today's bundles discount, gift
  // or both — and a meta description promising a price cut outlives the campaign that
  // made it true. The claim lives on the page, where it is read from the combos
  // themselves.
  description:
    "Curated sets of Toke Cosmetics favourites, boxed together so a whole routine arrives in one parcel.",
  path: "/combo",
});

const CRUMBS = [
  { name: "Home", path: "/" },
  { name: "Combo Deals", path: "/combo" },
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
  const anyGift = combos.some((c) => comboGift(c) !== null);
  const anyDiscount = combos.some((c) => comboSavingPercent(c.pricing) > 0);
  const eyebrow = anyDiscount
    ? "Buy the set, keep the change"
    : anyGift
      ? "Buy the set, keep the gift"
      : "Everything the routine needs, in one box";
  const reward =
    anyDiscount && anyGift
      ? " — some priced below what they cost separately, some with a free gift in the parcel"
      : anyDiscount
        ? " and priced below what they cost separately"
        : anyGift
          ? " and sent with a free gift in the parcel"
          : "";

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

      {/* THE COPY IS READ FROM THE COMBOS, not written once and left. "Priced below what
          they cost separately" was true of every bundle until one started rewarding with
          a gift instead — at which point the page was making a promise about a box sitting
          right under it that the box does not keep. Both sentences below are checked
          against what is actually on sale in THIS market today. */}
      <header className="mt-6 max-w-2xl">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
          {eyebrow}
        </p>
        <h1 className="mt-2 font-display text-3xl leading-tight sm:text-4xl">Combo Deals</h1>
        <p className="mt-3 text-muted">
          Routines we put together ourselves — the products that work best beside each
          other, boxed as one{reward}. Everything inside is the same full-size product you
          would buy on its own.
        </p>
      </header>

      {combos.length === 0 ? (
        <p className="mt-10 rounded-[var(--radius-card)] border border-dashed border-line bg-surface p-10 text-center text-muted">
          No combo deals are running right now. Check back soon.
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
