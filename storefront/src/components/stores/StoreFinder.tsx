"use client";

/**
 * The store locator's interactive half (Plan-42): the cascade, the results, and the
 * four things that can be on screen instead of results.
 *
 * ── IT HYDRATES, IT DOES NOT LOAD ───────────────────────────────────────────────────
 *
 * Every prop below was fetched by the server component that renders this one, so a
 * shared link (`/find-stores?country=nigeria&state=lagos&area=alimosho`) arrives with
 * its cards already in the HTML — indexable, and readable before hydration. This
 * component takes over from the first click and nothing more.
 *
 * ── STALE RESPONSES CANNOT WIN ──────────────────────────────────────────────────────
 *
 * The brief names the failure exactly: pick Alimosho, change to Ikeja, and Alimosho's
 * slower response overwrites Ikeja's. One monotonic counter guards every fetch on this
 * page — a response applies only while its ticket is still the current one, and any
 * later interaction, at any level of the cascade, invalidates it. The in-flight
 * request is aborted as well, which saves the round trip; the counter is what makes it
 * CORRECT, because an abort that loses the race still resolves.
 *
 * ── PICK ≠ LOAD ─────────────────────────────────────────────────────────────────────
 *
 * `pickCountry` is "the reader chose this" and refuses a re-pick of the current value;
 * `loadCountry` is "fetch what this needs" and refuses nothing. They are separate
 * because a RETRY re-runs the load for the value already chosen, and the first version
 * of this file routed the retry through the pick — whose guard read the slug from a
 * closure that the `setState` just before it had not updated, and returned. Every
 * "Try again" on a failed state or LGA load silently did nothing. The split is what
 * makes that impossible to reintroduce by accident.
 *
 * ── THE URL IS THE SELECTION ────────────────────────────────────────────────────────
 *
 * Written with `history.replaceState`, not `router.replace`: a Next navigation would
 * re-run the server component and refetch everything this component just fetched, and
 * the reader would watch their own click load twice. `replaceState` rather than
 * `pushState` because three cascading pickers would otherwise bury the previous page
 * under a dozen history entries — Back should leave the locator, not walk it backwards.
 */
import { useCallback, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Skeleton } from "@/components/ui/Skeleton";
import { StoreCard } from "@/components/stores/StoreCard";
import { PlacePicker } from "@/components/stores/PlacePicker";
import {
  humaniseSlug,
  lowerLabel,
  placeLabel,
  selectionQuery,
  type PlacesResponse,
  type StorePage,
  type StorePlace,
} from "@/lib/stores";

export interface StoreFinderProps {
  countries: StorePlace[];
  /** Everything the server already resolved for the incoming URL. */
  initial: {
    country: string | null;
    state: string | null;
    area: string | null;
    states: PlacesResponse | null;
    areas: PlacesResponse | null;
    stores: StorePage | null;
    /** Set when the server's store fetch failed outright, so the client can offer a
     *  retry instead of pretending the place is empty. */
    storesFailed: boolean;
    /** Set when any level of the cascade failed to load server-side. The pickers then
     *  say so and offer a retry, instead of an empty list that reads as "no stores". */
    placesFailed: boolean;
    /** The `?area=` slug the URL named that no longer resolves — the results are the
     *  whole state's, and the reader is told why. */
    staleArea: string | null;
  };
}

interface Level {
  items: StorePlace[];
  /** The country's own word for this level — "LGA", "County", "Province". */
  label: string;
}

interface Ticket {
  seq: number;
  signal: AbortSignal;
}

const GENERIC_ERROR = "We could not load that just now.";

export function StoreFinder({ countries: initialCountries, initial }: StoreFinderProps) {
  const pathname = usePathname();

  // Countries are state, not a prop read straight through, because the country list
  // is the one level a retry can have to refetch when the server's own fetch failed.
  const [countries, setCountries] = useState<StorePlace[]>(initialCountries);
  const [countrySlug, setCountrySlug] = useState<string | null>(initial.country);
  const [stateSlug, setStateSlug] = useState<string | null>(initial.state);
  const [areaSlug, setAreaSlug] = useState<string | null>(initial.area);

  const [states, setStates] = useState<Level | null>(levelFrom(initial.states, "State"));
  const [areas, setAreas] = useState<Level | null>(levelFrom(initial.areas, "Area"));
  const [stores, setStores] = useState<StorePage | null>(initial.stores);

  const [countriesLoading, setCountriesLoading] = useState(false);
  const [statesLoading, setStatesLoading] = useState(false);
  const [areasLoading, setAreasLoading] = useState(false);
  const [storesLoading, setStoresLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const [placesError, setPlacesError] = useState<string | null>(
    initial.placesFailed ? GENERIC_ERROR : null,
  );
  const [storesError, setStoresError] = useState<string | null>(
    initial.storesFailed ? GENERIC_ERROR : null,
  );
  // A one-line note above the results — today only "your bookmark named an LGA that is
  // gone, here is the whole state". Cleared by the first interaction, because after
  // that the results are the reader's own choice and the note would be about nothing.
  const [notice, setNotice] = useState<string | null>(
    initial.staleArea && initial.states
      ? `We couldn't find "${humaniseSlug(initial.staleArea)}" — showing every store in ${
          initial.states.items.find((s) => s.slug === initial.state)?.name ?? "the state"
        } instead.`
      : null,
  );

  /** The ticket every fetch holds. Bumped by every interaction. */
  const seqRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const country = countries.find((c) => c.slug === countrySlug) ?? null;
  const state = states?.items.find((s) => s.slug === stateSlug) ?? null;
  const area = areas?.items.find((a) => a.slug === areaSlug) ?? null;

  // The area picker exists only where the chosen state actually has stocked areas.
  // GB/US/CA states have no LGAs at all, so a third dropdown there would be a control
  // that can never be filled — the search runs at state level instead.
  const showAreas = Boolean(state?.has_children);

  const stateLabel = states?.label ?? country?.state_label ?? "State";
  const areaLabel = areas?.label ?? country?.area_label ?? "Area";

  const chosenPlace = placeLabel({
    area: area?.name,
    state: state?.name,
    country: country?.name,
  });

  /**
   * A fresh ticket, with the previous request abandoned.
   *
   * IT ALSO CLEARS THE SPINNERS, and that is not tidiness. `runSearch`'s `finally`
   * deliberately leaves `storesLoading` alone when its ticket has been superseded —
   * otherwise a slow loser would switch off the spinner belonging to the request that
   * beat it. The consequence is that abandoning a search WITHOUT starting another one
   * (changing country, "Change location") would leave the skeleton on screen forever.
   * Resetting here means every interaction starts from a known state, and the handlers
   * that do start a new request switch their own spinner straight back on.
   */
  const nextTicket = useCallback((): Ticket => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    seqRef.current += 1;
    setCountriesLoading(false);
    setStatesLoading(false);
    setAreasLoading(false);
    setStoresLoading(false);
    setNotice(null);
    return { seq: seqRef.current, signal: controller.signal };
  }, []);

  const syncUrl = useCallback(
    (sel: { country?: string | null; state?: string | null; area?: string | null }) => {
      const qs = selectionQuery(sel);
      window.history.replaceState(null, "", qs ? `${pathname}?${qs}` : pathname);
    },
    [pathname],
  );

  const runSearch = useCallback(
    async (
      sel: { country: string; state?: string | null; area?: string | null },
      ticket: Ticket,
    ) => {
      setStoresLoading(true);
      setStoresError(null);
      try {
        const res = await fetch(`/api/stores?${selectionQuery(sel)}`, {
          signal: ticket.signal,
        });
        const data = res.ok ? ((await res.json()) as StorePage) : null;
        if (ticket.seq !== seqRef.current) return; // superseded
        if (!data) {
          setStores(null);
          setStoresError(GENERIC_ERROR);
          return;
        }
        setStores(data);
      } catch {
        // An abort is the expected path when a newer pick supersedes this one, and it
        // must not paint an error over the newer request's results.
        if (ticket.seq !== seqRef.current) return;
        setStores(null);
        setStoresError(GENERIC_ERROR);
      } finally {
        if (ticket.seq === seqRef.current) setStoresLoading(false);
      }
    },
    [],
  );

  const loadPlaces = useCallback(
    async (
      sel: { country?: string | null; state?: string | null },
      ticket: Ticket,
    ): Promise<PlacesResponse | null> => {
      const qs = selectionQuery(sel);
      try {
        const res = await fetch(`/api/stores/places${qs ? `?${qs}` : ""}`, {
          signal: ticket.signal,
        });
        if (!res.ok) throw new Error("bad status");
        return (await res.json()) as PlacesResponse;
      } catch {
        return null;
      }
    },
    [],
  );

  // ── loads: fetch what a level needs, no questions asked ─────────────────────

  async function loadCountries() {
    const ticket = nextTicket();
    setPlacesError(null);
    setCountriesLoading(true);
    const data = await loadPlaces({}, ticket);
    if (ticket.seq !== seqRef.current) return;
    setCountriesLoading(false);
    if (!data) {
      setPlacesError(GENERIC_ERROR);
      return;
    }
    setCountries(data.items);
  }

  async function loadCountry(slug: string) {
    const ticket = nextTicket();
    // Everything below the changed level goes at once — the brief is explicit that a
    // previous place's results must never survive the change that invalidated them.
    setCountrySlug(slug);
    setStateSlug(null);
    setAreaSlug(null);
    setStates(null);
    setAreas(null);
    setStores(null);
    setStoresError(null);
    setPlacesError(null);
    setStatesLoading(true);
    syncUrl({ country: slug });

    const data = await loadPlaces({ country: slug }, ticket);
    if (ticket.seq !== seqRef.current) return;
    setStatesLoading(false);
    if (!data) {
      setPlacesError(GENERIC_ERROR);
      return;
    }
    setStates(levelFrom(data, "State"));
  }

  async function loadState(slug: string) {
    const ticket = nextTicket();
    const picked = states?.items.find((s) => s.slug === slug) ?? null;
    setStateSlug(slug);
    setAreaSlug(null);
    setAreas(null);
    setStores(null);
    setStoresError(null);
    setPlacesError(null);
    syncUrl({ country: countrySlug, state: slug });

    if (!countrySlug) return;

    // A state with no stocked areas IS the finest place — search it now rather than
    // rendering a third picker with nothing in it.
    if (!picked?.has_children) {
      await runSearch({ country: countrySlug, state: slug }, ticket);
      return;
    }

    setAreasLoading(true);
    const data = await loadPlaces({ country: countrySlug, state: slug }, ticket);
    if (ticket.seq !== seqRef.current) return;
    setAreasLoading(false);
    if (!data) {
      setPlacesError(GENERIC_ERROR);
      return;
    }
    setAreas(levelFrom(data, "Area"));
  }

  async function loadArea(slug: string) {
    const ticket = nextTicket();
    setAreaSlug(slug);
    setStores(null);
    setStoresError(null);
    syncUrl({ country: countrySlug, state: stateSlug, area: slug });
    if (!countrySlug) return;
    await runSearch({ country: countrySlug, state: stateSlug, area: slug }, ticket);
  }

  // ── picks: a reader's choice, which a re-pick of the same value is not ──────

  function pickCountry(slug: string) {
    if (slug !== countrySlug) void loadCountry(slug);
  }
  function pickState(slug: string) {
    if (slug !== stateSlug) void loadState(slug);
  }
  function pickArea(slug: string) {
    if (slug !== areaSlug) void loadArea(slug);
  }

  // ── retries ─────────────────────────────────────────────────────────────────

  function retrySearch() {
    if (!countrySlug) return;
    void runSearch(
      { country: countrySlug, state: stateSlug, area: areaSlug },
      nextTicket(),
    );
  }

  /** Re-run whichever cascade level failed: the one below the deepest choice made. */
  function retryPlaces() {
    if (!countrySlug) void loadCountries();
    else if (stateSlug) void loadState(stateSlug);
    else void loadCountry(countrySlug);
  }

  async function showMore() {
    if (!stores?.next || loadingMore || !countrySlug) return;
    setLoadingMore(true);
    const seq = seqRef.current;
    const qs = selectionQuery({ country: countrySlug, state: stateSlug, area: areaSlug });
    const page = nextPageOf(stores.next);
    try {
      const res = await fetch(`/api/stores?${qs}&page=${encodeURIComponent(page)}`);
      const data = res.ok ? ((await res.json()) as StorePage) : null;
      if (seq !== seqRef.current) return; // the selection moved on while we paged
      if (data) {
        setStores((prev) =>
          prev ? { ...data, results: [...prev.results, ...data.results] } : data,
        );
      }
    } catch {
      // Silent: the cards already on screen are still correct, and the button stays.
    } finally {
      // UNCONDITIONALLY, unlike the search spinners above: this flag only guards the
      // "Show more" button, and leaving it set because the selection moved on would
      // freeze that button on "Loading…" for the rest of the visit.
      setLoadingMore(false);
    }
  }

  /** The empty state's way out: drop the finest choice and put the reader back on the
   *  picker that made it. Takes a ticket like every other interaction, so a search
   *  still in flight cannot land on the cleared panel. */
  function chooseAnother() {
    if (areaSlug || stateSlug) {
      nextTicket();
      setStores(null);
      setStoresError(null);
    }
    if (areaSlug) {
      setAreaSlug(null);
      syncUrl({ country: countrySlug, state: stateSlug });
    } else if (stateSlug) {
      setStateSlug(null);
      setAreas(null);
      syncUrl({ country: countrySlug });
    }
    panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const searching = storesLoading;
  const results = stores?.results ?? [];
  const hasSearched = Boolean(
    stores || storesError || storesLoading || areaSlug || (stateSlug && !showAreas),
  );
  // A directory with nothing in it is a different page from one that failed to load,
  // and both are different from "you have not chosen yet".
  const directoryEmpty = countries.length === 0 && !placesError && !countriesLoading;

  const status = useMemo(() => {
    if (searching) return "Searching for stores…";
    if (storesError) return "The stores could not be loaded.";
    if (!hasSearched) return "";
    return results.length === 0
      ? `No stores found in ${chosenPlace}.`
      : `${stores?.count ?? results.length} ${(stores?.count ?? results.length) === 1 ? "store" : "stores"} in ${chosenPlace}.`;
  }, [searching, storesError, hasSearched, results.length, stores?.count, chosenPlace]);

  // "Nothing here yet" is only true once a level has actually loaded.
  const emptyText = placesError ? "Couldn't load" : undefined;

  return (
    <>
      <div ref={panelRef} className="scroll-mt-28">
        <div className="rounded-[var(--radius-card)] border border-line bg-surface/70 p-5 shadow-sm backdrop-blur-sm sm:p-7">
          {/* A named group, so a screen reader hears "Choose a location" before the
              three pickers and the header's own country/currency select is never
              mistaken for the first step of the cascade. */}
          <div
            role="group"
            aria-label="Choose a location"
            className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3"
          >
            <PlacePicker
              step={1}
              label="Country"
              placeholder="Choose your country"
              emptyText={emptyText}
              options={countries}
              value={countrySlug}
              onChange={pickCountry}
              loading={countriesLoading}
            />
            <PlacePicker
              step={2}
              label={stateLabel}
              placeholder={
                countrySlug ? `Choose your ${lowerLabel(stateLabel)}` : "Choose a country first"
              }
              emptyText={emptyText}
              options={states?.items ?? []}
              value={stateSlug}
              onChange={pickState}
              disabled={!countrySlug}
              loading={statesLoading}
            />
            {/* Rendered only where the country has them, so the row never holds a
                control that can never be used. */}
            {showAreas ? (
              <PlacePicker
                step={3}
                label={areaLabel}
                placeholder={`Choose your ${lowerLabel(areaLabel)}`}
                emptyText={emptyText}
                options={areas?.items ?? []}
                value={areaSlug}
                onChange={pickArea}
                disabled={!stateSlug}
                loading={areasLoading}
              />
            ) : (
              <div className="hidden lg:block" aria-hidden />
            )}
          </div>

          {placesError && (
            <p
              role="alert"
              className="mt-4 flex flex-wrap items-center gap-3 rounded-[var(--radius-card)] bg-beige px-4 py-3 text-sm"
            >
              <span>{placesError}</span>
              <button
                type="button"
                onClick={retryPlaces}
                className="font-medium text-accent underline underline-offset-4"
              >
                Try again
              </button>
            </p>
          )}
        </div>
      </div>

      {/* One polite live region for the whole panel: a reader hears "Searching…" then
          the count, rather than every card being announced as it mounts. */}
      <p role="status" aria-live="polite" className="sr-only">
        {status}
      </p>

      <div className="mt-10">
        {searching ? (
          <ResultsSkeleton />
        ) : storesError ? (
          <ErrorState onRetry={retrySearch} />
        ) : !hasSearched ? (
          <IntroState
            empty={directoryEmpty}
            country={country}
            stateLabel={stateLabel}
            areaLabel={areaLabel}
          />
        ) : results.length === 0 ? (
          <EmptyState place={chosenPlace} onChooseAnother={chooseAnother} />
        ) : (
          <>
            {notice && (
              <p
                role="status"
                className="mb-5 rounded-[var(--radius-card)] border border-line bg-beige/60 px-4 py-3 text-sm text-muted"
              >
                {notice}
              </p>
            )}
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-display text-2xl">
                {stores?.count ?? results.length}{" "}
                {(stores?.count ?? results.length) === 1 ? "store" : "stores"} in{" "}
                {chosenPlace}
              </h2>
              <button
                type="button"
                onClick={chooseAnother}
                className="text-sm text-muted underline underline-offset-4 transition hover:text-accent"
              >
                Change location
              </button>
            </div>
            <ul className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
              {results.map((store, index) => (
                <li
                  key={store.id}
                  className="store-card-in"
                  // Capped: past the first row or two the stagger stops reading as
                  // rhythm and starts reading as the page being slow.
                  style={{ "--card-index": Math.min(index, 5) } as React.CSSProperties}
                >
                  <StoreCard store={store} index={index + 1} />
                </li>
              ))}
            </ul>
            {stores?.next && (
              <div className="mt-8 text-center">
                <button
                  type="button"
                  onClick={showMore}
                  disabled={loadingMore}
                  className="rounded-full border border-line px-6 py-3 text-sm font-medium transition hover:border-accent hover:text-accent disabled:opacity-60"
                >
                  {loadingMore ? "Loading…" : "Show more stores"}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

/** The page number inside DRF's `next` link. Absolute in practice, parsed against the
 *  current origin anyway so a relative one cannot throw, and defaulted rather than
 *  allowed to reject — this runs inside a click handler, where an exception is a button
 *  that silently stops working. */
function nextPageOf(next: string): string {
  try {
    return new URL(next, window.location.origin).searchParams.get("page") ?? "2";
  } catch {
    return "2";
  }
}

function levelFrom(response: PlacesResponse | null, fallback: string): Level | null {
  if (!response) return null;
  return { items: response.items, label: response.label || fallback };
}

/** What the page shows before anything is chosen — the brief's "the page should feel
 *  complete even before the customer makes a selection". Worded in the chosen
 *  country's own terms, because "state and local area" is wrong for a UK reader whose
 *  next two pickers say "Country" and "County". */
function IntroState({
  empty,
  country,
  stateLabel,
  areaLabel,
}: {
  empty: boolean;
  country: StorePlace | null;
  stateLabel: string;
  areaLabel: string;
}) {
  let title = "Find a store near you";
  let body =
    "Choose your country, state and local area to discover Toke Cosmetics stores and authorized distributors near you.";
  if (empty) {
    title = "Stores are coming";
    body =
      "We are still compiling the list of shops and distributors that carry Toke Cosmetics. Until it is here, we ship nationwide and worldwide from our online store.";
  } else if (country) {
    const levels = country.has_children
      ? `${lowerLabel(stateLabel)} and ${lowerLabel(areaLabel)}`
      : lowerLabel(stateLabel);
    body = `Choose your ${levels} to see the Toke Cosmetics stores and authorized distributors closest to you.`;
  }
  return (
    <div className="rounded-[var(--radius-card)] border border-dashed border-line bg-beige/40 px-6 py-14 text-center">
      <CompassMark />
      <h2 className="mt-5 font-display text-2xl">{title}</h2>
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted">{body}</p>
      {empty && (
        <Link
          href="/products"
          className="mt-7 inline-block rounded-full bg-accent px-6 py-3 text-sm font-medium text-surface transition hover:bg-accent-strong"
        >
          Shop online
        </Link>
      )}
    </div>
  );
}

function EmptyState({
  place,
  onChooseAnother,
}: {
  place: string;
  onChooseAnother: () => void;
}) {
  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface px-6 py-14 text-center">
      <CompassMark />
      <h2 className="mt-5 font-display text-2xl">No stores found in this area</h2>
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted">
        We couldn&rsquo;t find a Toke Cosmetics store or authorized distributor in{" "}
        {place}. We ship there — and to the rest of the world — from our online store.
      </p>
      <div className="mt-7 flex flex-wrap justify-center gap-3">
        <button
          type="button"
          onClick={onChooseAnother}
          className="rounded-full bg-accent px-6 py-3 text-sm font-medium text-surface transition hover:bg-accent-strong"
        >
          Choose another location
        </button>
        <Link
          href="/products"
          className="rounded-full border border-line px-6 py-3 text-sm font-medium transition hover:border-accent hover:text-accent"
        >
          Shop online instead
        </Link>
      </div>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-[var(--radius-card)] border border-line bg-surface px-6 py-14 text-center"
    >
      <h2 className="font-display text-2xl">We couldn&rsquo;t load the stores</h2>
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted">
        Something went wrong on our side. Your connection may also have dropped.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-7 rounded-full bg-accent px-6 py-3 text-sm font-medium text-surface transition hover:bg-accent-strong"
      >
        Try again
      </button>
    </div>
  );
}

function ResultsSkeleton() {
  return (
    <ul className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3" aria-hidden>
      {[0, 1, 2].map((i) => (
        <li
          key={i}
          className="rounded-[var(--radius-card)] border border-line bg-surface p-6 sm:p-7"
        >
          <Skeleton className="h-3 w-8" />
          <Skeleton className="mt-3 h-6 w-2/3" />
          <Skeleton className="mt-6 h-4 w-full" />
          <Skeleton className="mt-2 h-4 w-4/5" />
          <Skeleton className="mt-6 h-4 w-1/2" />
          <div className="mt-8 flex gap-2">
            <Skeleton className="h-9 w-28 rounded-full" />
            <Skeleton className="h-9 w-32 rounded-full" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function CompassMark() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 48 48"
      className="mx-auto size-12 text-accent/50"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.25"
    >
      <circle cx="24" cy="24" r="17" />
      <path d="m29.5 18.5-3 8-8 3 3-8 8-3Z" strokeLinejoin="round" />
    </svg>
  );
}
