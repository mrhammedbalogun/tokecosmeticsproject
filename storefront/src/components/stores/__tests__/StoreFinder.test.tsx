import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { StoreFinder } from "@/components/stores/StoreFinder";
import type { PlacesResponse, StoreCardData, StorePage, StorePlace } from "@/lib/stores";

vi.mock("next/navigation", () => ({ usePathname: () => "/find-stores" }));

type Route = { status: number; body: unknown };

/** Routes fetch calls by URL — every call this component makes is a GET. Same shape as
 *  the address-form tests. A route may be a LIST of responses, served in order and the
 *  last one repeated: "fails, then succeeds" is what every retry test needs to say. */
function mockFetch(routes: Record<string, Route | Route[]>) {
  const served: Record<string, number> = {};
  const f = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const entry = routes[url];
    if (!entry) return Promise.reject(new Error(`unexpected fetch: ${url}`));
    const list = Array.isArray(entry) ? entry : [entry];
    const route = list[Math.min(served[url] ?? 0, list.length - 1)];
    served[url] = (served[url] ?? 0) + 1;
    return Promise.resolve(
      new Response(JSON.stringify(route.body), {
        status: route.status,
        headers: { "content-type": "application/json" },
      }),
    );
  });
  global.fetch = f as unknown as typeof fetch;
  return f;
}

/** A fetch whose responses resolve only when the test says so — the only way to prove
 *  the stale-response guard, which is about ORDER of resolution and nothing else. */
function deferredFetch() {
  const pending: { url: string; resolve: (body: unknown) => void }[] = [];
  global.fetch = vi.fn(
    (input: RequestInfo | URL) =>
      new Promise((resolve) => {
        pending.push({
          url: typeof input === "string" ? input : input.toString(),
          resolve: (body) =>
            resolve(
              new Response(JSON.stringify(body), {
                status: 200,
                headers: { "content-type": "application/json" },
              }),
            ),
        });
      }),
  ) as unknown as typeof fetch;
  return pending;
}

const NIGERIA: StorePlace = {
  slug: "nigeria",
  name: "Nigeria",
  code: "NG",
  store_count: 3,
  has_children: true,
  state_label: "State",
  area_label: "LGA",
};

const LAGOS: StorePlace = { slug: "lagos", name: "Lagos", store_count: 3, has_children: true };
const ALIMOSHO: StorePlace = { slug: "alimosho", name: "Alimosho", store_count: 1, has_children: false };
const IKEJA: StorePlace = { slug: "ikeja", name: "Ikeja", store_count: 2, has_children: false };

/** A GB-shaped state: no LGAs under it, so choosing it must search immediately. */
const GREATER_LONDON: StorePlace = {
  slug: "greater-london",
  name: "Greater London",
  store_count: 1,
  has_children: false,
};

function places(level: PlacesResponse["level"], items: StorePlace[], label?: string): PlacesResponse {
  return { level, parent: null, label, items };
}

function card(id: number, name: string, type: StoreCardData["store_type"] = "distributor"): StoreCardData {
  return {
    id,
    name,
    store_type: type,
    store_type_label: type === "toke_store" ? "Toke Store" : "Authorized Distributor",
    address: "12 Hassan Balogun Street, Isheri-Olofin, Ikotun",
    city: "",
    area: "Alimosho",
    state: "Lagos",
    country: "Nigeria",
    country_code: "NG",
    phone: "+2348023900964",
    phone_display: "0802 390 0964",
    phone_alt: "",
    phone_alt_display: "",
    whatsapp_url: "",
    opening_hours: "",
    directions_url: "https://www.google.com/maps/search/?api=1&query=x",
  };
}

function page(results: StoreCardData[], next: string | null = null): StorePage {
  return { count: results.length, next, previous: null, results };
}

const BASE_INITIAL = {
  country: null,
  state: null,
  area: null,
  states: null,
  areas: null,
  stores: null,
  storesFailed: false,
  placesFailed: false,
  staleArea: null,
};

/** Open a picker and click one of its options.
 *
 *  The collapsed control is a button whose accessible name is "<label> <current value>"
 *  — that is what a combobox is supposed to announce. It also means the names overlap
 *  ("State — Choose a country first" contains the word "country"), so every selector
 *  here is ANCHORED to the label. */
async function pick(label: RegExp, optionName: RegExp) {
  // Waits for the picker to be BOTH present and enabled. While its level is loading it
  // is disabled and reads "<label> Loading…", and a click on a disabled button does
  // nothing — so a helper that clicked the first match it found would silently no-op.
  // The label itself can change too: the state picker becomes "County" only once the
  // response carries the country's own word for the level.
  let trigger!: HTMLElement;
  await waitFor(() => {
    trigger = screen.getByRole("combobox", { name: label });
    expect(trigger).toBeEnabled();
  });
  fireEvent.click(trigger);
  const option = await screen.findByRole("option", { name: optionName });
  fireEvent.click(option);
}

const originalFetch = global.fetch;
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("StoreFinder", () => {
  it("shows the intro state, not an empty results list, before anything is chosen", () => {
    render(<StoreFinder countries={[NIGERIA]} initial={BASE_INITIAL} />);
    expect(screen.getByText(/find a store near you/i)).toBeInTheDocument();
    expect(screen.queryByText(/no stores found/i)).not.toBeInTheDocument();
  });

  it("locks each picker until the level above it is chosen", () => {
    render(<StoreFinder countries={[NIGERIA]} initial={BASE_INITIAL} />);
    expect(screen.getByRole("combobox", { name: /^Country/ })).toBeEnabled();
    expect(screen.getByRole("combobox", { name: /^State/ })).toBeDisabled();
    // The LGA picker does not exist at all until a state with LGAs is chosen — an
    // always-present third dropdown would be a control that can never be filled.
    expect(screen.queryByRole("combobox", { name: /^LGA/ })).not.toBeInTheDocument();
  });

  it("cascades country → state → LGA and shows the stores in the LGA", async () => {
    mockFetch({
      "/api/stores/places?country=nigeria": { status: 200, body: places("state", [LAGOS], "State") },
      "/api/stores/places?country=nigeria&state=lagos": {
        status: 200,
        body: places("area", [ALIMOSHO, IKEJA], "LGA"),
      },
      "/api/stores?country=nigeria&state=lagos&area=alimosho": {
        status: 200,
        body: page([card(1, "Beauty Hub Alimosho")]),
      },
    });

    render(<StoreFinder countries={[NIGERIA]} initial={BASE_INITIAL} />);

    await pick(/^Country/, /^Nigeria/);
    await pick(/^State/, /^Lagos/);
    await pick(/^LGA/, /^Alimosho/);

    expect(await screen.findByText("Beauty Hub Alimosho")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /1 store in Alimosho, Lagos/i })).toBeInTheDocument();
  });

  it("searches at state level when the state has no districts", async () => {
    const gb: StorePlace = { ...NIGERIA, slug: "united-kingdom", name: "United Kingdom", code: "GB" };
    mockFetch({
      "/api/stores/places?country=united-kingdom": {
        status: 200,
        body: places("state", [GREATER_LONDON], "County"),
      },
      "/api/stores?country=united-kingdom&state=greater-london": {
        status: 200,
        body: page([card(9, "Toke London", "toke_store")]),
      },
    });

    render(<StoreFinder countries={[gb]} initial={BASE_INITIAL} />);
    await pick(/^Country/, /United Kingdom/);
    await pick(/^County/, /Greater London/);

    expect(await screen.findByText("Toke London")).toBeInTheDocument();
  });

  it("shows the empty state, not a blank page, when a place holds no stores", async () => {
    mockFetch({
      "/api/stores/places?country=nigeria": { status: 200, body: places("state", [LAGOS], "State") },
      "/api/stores/places?country=nigeria&state=lagos": {
        status: 200,
        body: places("area", [ALIMOSHO], "LGA"),
      },
      "/api/stores?country=nigeria&state=lagos&area=alimosho": { status: 200, body: page([]) },
    });

    render(<StoreFinder countries={[NIGERIA]} initial={BASE_INITIAL} />);
    await pick(/^Country/, /^Nigeria/);
    await pick(/^State/, /^Lagos/);
    await pick(/^LGA/, /^Alimosho/);

    expect(await screen.findByText(/no stores found in this area/i)).toBeInTheDocument();
    // Named twice on purpose — once in the visible copy, once in the polite live region
    // that tells a screen-reader user the search finished.
    expect(screen.getAllByText(/Alimosho, Lagos/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /choose another location/i })).toBeInTheDocument();
  });

  it("offers a retry instead of a technical error when the store fetch fails", async () => {
    mockFetch({
      "/api/stores/places?country=nigeria": { status: 200, body: places("state", [LAGOS], "State") },
      "/api/stores/places?country=nigeria&state=lagos": {
        status: 200,
        body: places("area", [ALIMOSHO], "LGA"),
      },
      "/api/stores?country=nigeria&state=lagos&area=alimosho": {
        status: 500,
        body: { detail: "ProgrammingError: relation does not exist" },
      },
    });

    render(<StoreFinder countries={[NIGERIA]} initial={BASE_INITIAL} />);
    await pick(/^Country/, /^Nigeria/);
    await pick(/^State/, /^Lagos/);
    await pick(/^LGA/, /^Alimosho/);

    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
    // Nothing from the upstream body reaches the customer.
    expect(screen.queryByText(/ProgrammingError/)).not.toBeInTheDocument();
  });

  it("clears the previous results the moment the state changes", async () => {
    mockFetch({
      "/api/stores/places?country=nigeria&state=lagos": {
        status: 200,
        body: places("area", [ALIMOSHO, IKEJA], "LGA"),
      },
      "/api/stores?country=nigeria&state=lagos&area=ikeja": {
        status: 200,
        body: page([card(2, "Ikeja Store")]),
      },
    });

    render(
      <StoreFinder
        countries={[NIGERIA]}
        initial={{
          ...BASE_INITIAL,
          country: "nigeria",
          state: "lagos",
          area: "alimosho",
          states: places("state", [LAGOS], "State"),
          areas: places("area", [ALIMOSHO, IKEJA], "LGA"),
          stores: page([card(1, "Alimosho Store")]),
        }}
      />,
    );
    expect(screen.getByText("Alimosho Store")).toBeInTheDocument();

    await pick(/^LGA/, /^Ikeja/);
    await waitFor(() => expect(screen.queryByText("Alimosho Store")).not.toBeInTheDocument());
    expect(await screen.findByText("Ikeja Store")).toBeInTheDocument();
  });

  it("does not let a slow earlier request overwrite the newer selection", async () => {
    const pending = deferredFetch();

    render(
      <StoreFinder
        countries={[NIGERIA]}
        initial={{
          ...BASE_INITIAL,
          country: "nigeria",
          state: "lagos",
          states: places("state", [LAGOS], "State"),
          areas: places("area", [ALIMOSHO, IKEJA], "LGA"),
        }}
      />,
    );

    await pick(/^LGA/, /^Alimosho/);
    await pick(/^LGA/, /^Ikeja/);

    const alimosho = pending.find((p) => p.url.includes("area=alimosho"));
    const ikeja = pending.find((p) => p.url.includes("area=ikeja"));
    expect(alimosho && ikeja).toBeTruthy();

    // Ikeja answers first, then Alimosho's stale response lands.
    ikeja!.resolve(page([card(2, "Ikeja Store")]));
    expect(await screen.findByText("Ikeja Store")).toBeInTheDocument();
    alimosho!.resolve(page([card(1, "Alimosho Store")]));

    await waitFor(() => expect(screen.getByText("Ikeja Store")).toBeInTheDocument());
    expect(screen.queryByText("Alimosho Store")).not.toBeInTheDocument();
  });

  it("does not leave the loading skeleton up when a search is abandoned", async () => {
    // The spinner belongs to the newest request, so a superseded one deliberately does
    // not switch it off — which means abandoning a search WITHOUT starting another
    // (here: changing country) has to clear it, or the skeleton never leaves.
    const pending = deferredFetch();

    render(
      <StoreFinder
        countries={[NIGERIA, { ...NIGERIA, slug: "ghana", name: "Ghana", code: "GH" }]}
        initial={{
          ...BASE_INITIAL,
          country: "nigeria",
          state: "lagos",
          states: places("state", [LAGOS], "State"),
          areas: places("area", [ALIMOSHO], "LGA"),
        }}
      />,
    );

    await pick(/^LGA/, /^Alimosho/);
    expect(pending.some((r) => r.url.includes("area=alimosho"))).toBe(true);

    await pick(/^Country/, /^Ghana/);
    // The intro is back, which it cannot be while the component still thinks it is
    // searching — that state renders the skeleton instead.
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /find a store near you/i })).toBeInTheDocument(),
    );
  });

  it("pages the results rather than capping them", async () => {
    mockFetch({
      "/api/stores?country=nigeria&state=lagos&area=alimosho&page=2": {
        status: 200,
        body: { ...page([card(2, "Second Page Store")]), count: 2 },
      },
    });

    render(
      <StoreFinder
        countries={[NIGERIA]}
        initial={{
          ...BASE_INITIAL,
          country: "nigeria",
          state: "lagos",
          area: "alimosho",
          states: places("state", [LAGOS], "State"),
          areas: places("area", [ALIMOSHO], "LGA"),
          stores: {
            ...page([card(1, "First Page Store")]),
            count: 2,
            next: "http://api.local/api/v1/stores/?country=nigeria&page=2",
          },
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /show more stores/i }));

    expect(await screen.findByText("Second Page Store")).toBeInTheDocument();
    // Appended, not replaced.
    expect(screen.getByText("First Page Store")).toBeInTheDocument();
  });

  it("retries a failed LGA load for the state already chosen", async () => {
    // The first version routed this retry through the pick handler, whose
    // same-value guard read a stale closure and returned — every "Try again" on a
    // failed cascade level did nothing. This is the test that would have caught it.
    mockFetch({
      "/api/stores/places?country=nigeria": { status: 200, body: places("state", [LAGOS], "State") },
      "/api/stores/places?country=nigeria&state=lagos": [
        { status: 500, body: { detail: "boom" } },
        { status: 200, body: places("area", [ALIMOSHO], "LGA") },
      ],
    });

    render(<StoreFinder countries={[NIGERIA]} initial={BASE_INITIAL} />);
    await pick(/^Country/, /^Nigeria/);
    await pick(/^State/, /^Lagos/);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not load/i);
    // The LGA picker is on screen but must not claim the state is empty.
    expect(screen.getByRole("combobox", { name: /^LGA/ })).toHaveTextContent(/couldn't load/i);

    fireEvent.click(within(alert).getByRole("button", { name: /try again/i }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    await pick(/^LGA/, /^Alimosho/);
    expect(screen.getByRole("combobox", { name: /^LGA/ })).toHaveTextContent("Alimosho");
  });

  it("offers a retry when the country list itself failed to load", async () => {
    mockFetch({
      "/api/stores/places": { status: 200, body: places("country", [NIGERIA]) },
    });

    render(<StoreFinder countries={[]} initial={{ ...BASE_INITIAL, placesFailed: true }} />);
    // A failed load is NOT an empty directory: no "Stores are coming", a Try-again instead.
    expect(screen.queryByText(/stores are coming/i)).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /^Country/ })).toHaveTextContent(/couldn't load/i);

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    await pick(/^Country/, /^Nigeria/);
    expect(screen.getByRole("combobox", { name: /^Country/ })).toHaveTextContent("Nigeria");
  });

  it("tells an empty directory apart from a failed one", () => {
    render(<StoreFinder countries={[]} initial={BASE_INITIAL} />);
    expect(screen.getByRole("heading", { name: /stores are coming/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });

  it("says which stale bookmark it fell back from, until the reader picks again", async () => {
    mockFetch({
      "/api/stores?country=nigeria&state=lagos&area=alimosho": {
        status: 200,
        body: page([card(1, "Beauty Hub Alimosho")]),
      },
    });
    render(
      <StoreFinder
        countries={[NIGERIA]}
        initial={{
          ...BASE_INITIAL,
          country: "nigeria",
          state: "lagos",
          states: places("state", [LAGOS], "State"),
          areas: places("area", [ALIMOSHO], "LGA"),
          stores: page([card(1, "Lagos Wide Store")]),
          staleArea: "ikotun-egbe",
        }}
      />,
    );
    expect(screen.getByText(/couldn't find "Ikotun Egbe" — showing every store in Lagos/i))
      .toBeInTheDocument();

    await pick(/^LGA/, /^Alimosho/);
    await screen.findByText("Beauty Hub Alimosho");
    expect(screen.queryByText(/Ikotun Egbe/)).not.toBeInTheDocument();
  });

  it("speaks the chosen country's own words for its levels", () => {
    const gb: StorePlace = {
      ...NIGERIA, slug: "united-kingdom", name: "United Kingdom", code: "GB",
      has_children: false, state_label: "Country", area_label: "District",
    };
    render(
      <StoreFinder
        countries={[gb]}
        initial={{ ...BASE_INITIAL, country: "united-kingdom",
          states: places("state", [GREATER_LONDON], "County") }}
      />,
    );
    // "LGA"-style acronyms keep their case; ordinary words go lowercase mid-sentence.
    expect(screen.getByRole("combobox", { name: /^County/ })).toHaveTextContent("Choose your county");
    expect(screen.getByText(/choose your county to see/i)).toBeInTheDocument();
  });

  it("renders a card a customer can act on without exposing internal ids", () => {
    render(
      <StoreFinder
        countries={[NIGERIA]}
        initial={{
          ...BASE_INITIAL,
          country: "nigeria",
          state: "lagos",
          area: "alimosho",
          states: places("state", [LAGOS], "State"),
          areas: places("area", [ALIMOSHO], "LGA"),
          stores: page([card(42, "Toke Ogudu Store", "toke_store")]),
        }}
      />,
    );

    const article = screen.getByRole("article");
    expect(within(article).getByText("Toke Store")).toBeInTheDocument();
    // The prettified number is what a reader sees; the diallable E.164 is what the link
    // carries.
    expect(within(article).getAllByText("0802 390 0964").length).toBeGreaterThan(0);
    expect(within(article).getByRole("link", { name: /call store/i })).toHaveAttribute(
      "href",
      "tel:+2348023900964",
    );
    expect(within(article).getByRole("link", { name: /get directions/i })).toHaveAttribute(
      "target",
      "_blank",
    );
    expect(article.textContent).not.toContain("42");
  });
});
