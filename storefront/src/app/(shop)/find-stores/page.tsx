import type { Metadata } from "next";
import { cookies } from "next/headers";
import { FadeUp } from "@/components/motion/Motion";
import { JsonLd } from "@/components/seo/JsonLd";
import { StoreFinder } from "@/components/stores/StoreFinder";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { breadcrumbJsonLd, pageMetadata, storeListJsonLd } from "@/lib/seo";
import {
  getPlaces,
  getStores,
  placeLabel,
  type PlacesResponse,
  type StorePage,
  type StorePlace,
} from "@/lib/stores";

/**
 * `/find-stores` — the public store locator (Plan-42). Reached from the header's `More`
 * menu (`lib/site-pages.ts`), and from whatever WhatsApp message someone pastes a
 * filtered link into.
 *
 * ── WHY THIS PAGE RESOLVES THE WHOLE SELECTION SERVER-SIDE ──────────────────────────
 *
 * `StoreFinder` could have fetched everything on mount and this file could have been
 * twenty lines. It resolves here instead so that a link naming a place arrives with its
 * cards in the HTML: crawlable (the brief asks for a crawlable public page), readable
 * before hydration, and free of the load-spinner flash that a mount-fetch always shows
 * to the one reader who was sent a specific shop.
 *
 * ── EVERY SLUG IN THE URL IS TREATED AS A GUESS ─────────────────────────────────────
 *
 * A slug is resolved by looking it up in the list of places that actually hold stores,
 * never by trusting it. Renaming an LGA, or archiving the last store in one, turns a
 * bookmark into a slug nothing matches — and the answer to that is the next-widest
 * place ("here is everything in Lagos"), not a 404 and not an empty page. The backend
 * supports the wider query for exactly this reason; see `services.stores_in`.
 *
 * ── THE COUNTRY IS PRESELECTED, THE REST IS NOT ─────────────────────────────────────
 *
 * A reader shopping in NG lands with Nigeria already chosen, because the market cookie
 * already knows and asking again is a click spent on nothing. It is a DEFAULT, not a
 * selection: it is not written to the URL, and the intro state still stands until a
 * real choice is made.
 */
export const metadata: Metadata = pageMetadata({
  // BARE title. The root layout applies the `%s | Toke Cosmetics` template.
  title: "Find a Store",
  description:
    "Find Toke Cosmetics stores and authorized distributors near you — addresses, phone numbers and directions, by country, state and local area.",
  path: "/find-stores",
});

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/** One trimmed, LOWERCASED value from a search param. Lowercased because every slug
 *  the backend mints is lowercase and its own resolver is case-insensitive — a link
 *  hand-typed as `?state=Lagos` should land on Lagos here too, not on the intro. */
function one(value: string | string[] | undefined): string | null {
  if (typeof value === "string") return value.trim().toLowerCase() || null;
  if (Array.isArray(value)) return one(value[0]);
  return null;
}

export default async function FindStoresPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const market = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;

  const countryList = await getPlaces({}, market);
  const countries = countryList?.items ?? [];
  // Tracked separately from "empty": a failed level renders a Try-again, an empty one
  // renders "Nothing here yet", and confusing the two is how an outage reads as "no
  // stores in Nigeria".
  let placesFailed = countryList === null;

  // Asked-for country by slug or ISO code, else the reader's market, else nothing.
  const asked = one(params.country);
  const country =
    (asked && countries.find((c) => c.slug === asked || c.code?.toLowerCase() === asked)) ||
    countries.find((c) => c.code?.toUpperCase() === market.toUpperCase()) ||
    null;

  let states: PlacesResponse | null = null;
  let areas: PlacesResponse | null = null;
  let stores: StorePage | null = null;
  let storesFailed = false;
  let state: StorePlace | null = null;
  let area: StorePlace | null = null;
  let staleArea: string | null = null;

  if (country) {
    states = await getPlaces({ country: country.slug }, market);
    if (states === null) placesFailed = true;
    const askedState = one(params.state);
    state = askedState ? (states?.items.find((s) => s.slug === askedState) ?? null) : null;

    const askedArea = one(params.area);
    if (state?.has_children) {
      areas = await getPlaces({ country: country.slug, state: state.slug }, market);
      if (areas === null) placesFailed = true;
      area = askedArea ? (areas?.items.find((a) => a.slug === askedArea) ?? null) : null;
      // Only a stale bookmark when the level actually loaded — if the areas fetch
      // failed, the slug may be perfectly good and the reader is told about the
      // failure instead.
      if (askedArea && areas && area === null) staleArea = askedArea;
    }

    // Search at the narrowest place that resolved.
    //
    // A state with areas but none ASKED FOR is the one case that does not search: the
    // reader still has a picker to answer, and pre-filling the page with the whole
    // state's stores would make that picker look optional when it is the point of the
    // page. An area that WAS asked for and did not resolve is the opposite case — a
    // bookmark whose LGA has since been renamed or emptied — and there the state-wide
    // answer ("here is everything in Lagos") beats both a 404 and a blank panel. The
    // backend supports the wider query for exactly this; see `services.stores_in`.
    const searchable = area || staleArea || !state?.has_children;
    if (state && searchable) {
      stores = await getStores(
        { country: country.slug, state: state.slug, area: area?.slug },
        market,
      );
      storesFailed = stores === null;
    }
  }

  const chosen = placeLabel({
    area: area?.name,
    state: state?.name,
    country: country?.name,
  });

  return (
    <div className="bg-background">
      <JsonLd
        data={breadcrumbJsonLd([
          { name: "Home", path: "/" },
          { name: "Find a Store", path: "/find-stores" },
        ])}
      />
      {stores && stores.results.length > 0 && (
        <JsonLd data={storeListJsonLd(stores.results, "/find-stores")} />
      )}

      <Hero storeCount={countries.reduce((n, c) => n + c.store_count, 0)} />

      <section className="wrap pb-24">
        <div className="mx-auto max-w-6xl">
          {/* Server-rendered so a crawler and a JS-less reader both get the sentence
              that says what this page holds, whatever the island does after. */}
          {chosen && (
            <p className="sr-only">
              Toke Cosmetics stores and authorized distributors in {chosen}.
            </p>
          )}
          <StoreFinder
            countries={countries}
            initial={{
              country: country?.slug ?? null,
              state: state?.slug ?? null,
              area: area?.slug ?? null,
              states,
              areas,
              stores,
              storesFailed,
              placesFailed,
              staleArea,
            }}
          />
        </div>
      </section>
    </div>
  );
}

/**
 * Elegance over decoration, per the brief: type, whitespace and one hairline rule. No
 * photograph — the hero of a locator is the thing you came to use, and an image band
 * here would push the first picker below the fold on a phone.
 */
function Hero({ storeCount }: { storeCount: number }) {
  return (
    <section className="wrap border-b border-line pb-14 pt-16 sm:pt-20">
      <div className="mx-auto max-w-6xl">
        <FadeUp>
          <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted">
            Store Locator
          </p>
          <h1 className="mt-4 max-w-3xl font-display text-4xl leading-[1.1] sm:text-5xl lg:text-6xl">
            Find a Toke Cosmetics Store
          </h1>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-muted">
            Discover Toke Cosmetics stores and authorized distributors near you.
            {storeCount > 0 && (
              <>
                {" "}
                <span className="whitespace-nowrap">
                  {storeCount} {storeCount === 1 ? "location" : "locations"} and counting.
                </span>
              </>
            )}
          </p>
        </FadeUp>
      </div>
    </section>
  );
}
