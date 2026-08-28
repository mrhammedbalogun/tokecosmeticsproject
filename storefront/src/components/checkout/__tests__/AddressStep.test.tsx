import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CheckoutProvider, useCheckout } from "@/components/checkout/CheckoutContext";
import { AddressStep } from "@/components/checkout/AddressStep";
import type { Cart } from "@/lib/cart-types";

// Plan-32b slice 3: the Places assist is mocked at its one seam. Configured ON so the
// NG pin test below can exercise pick → pin → payload; the map loader resolves null,
// which must degrade to the "map could not load" fallback without breaking anything.
vi.mock("@/lib/googleMaps", () => ({
  mapsConfigured: vi.fn(() => true),
  loadGoogleMaps: vi.fn(async () => null),
  fetchStreetSuggestions: vi.fn(async () => [
    { id: "p1", mainText: "12 Allen Avenue", secondaryText: "Ikeja, Lagos" },
  ]),
  resolveSuggestion: vi.fn(async () => ({
    line1: "12 Allen Avenue",
    lat: 6.60184,
    lng: 3.35149,
    lgaName: "Agege Local Government Area",
    stateName: "Lagos",
  })),
}));

/** AddressStep reads the shopping country from useCart().cart.country — mock it the
 * same way CartView.test.tsx does so each test can pin the country independently. */
let mockCart: Cart;
vi.mock("@/hooks/useCart", () => ({
  useCart: () => ({
    cart: mockCart,
    isLoading: false,
    addItem: { mutate: vi.fn() },
    setQty: { mutate: vi.fn() },
  }),
}));

function makeCart(overrides: Partial<Cart> = {}): Cart {
  return {
    id: "cart-1",
    kind: "standard",
    status: "active",
    country: "GB",
    currency: "GBP",
    items: [],
    subtotal: "0.00",
    has_unavailable: false,
    ...overrides,
  };
}

/** Small harness exposing the checkout machine's completed/selections state next to
 * the real AddressStep, mirroring SignInStep.test.tsx's Harness pattern. */
function Harness() {
  const { completed, selections } = useCheckout();
  return (
    <div>
      <p data-testid="completed">{[...completed].sort().join(",")}</p>
      <p data-testid="addressId">{String(selections.addressId ?? "")}</p>
      <p data-testid="addressDisplay">{selections.addressDisplay ?? ""}</p>
      <AddressStep />
    </div>
  );
}

function renderHarness() {
  return render(
    <CheckoutProvider>
      <Harness />
    </CheckoutProvider>
  );
}

type Route = { status: number; body: unknown };

/** Routes fetch calls by "METHOD url" (GET and POST both hit /api/addresses, so a
 * URL-only map like SignInStep.test.tsx's isn't enough here). */
function mockFetch(routes: Record<string, Route>) {
  const f = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url}`;
    const route = routes[key];
    if (!route) return Promise.reject(new Error(`unexpected fetch: ${key}`));
    return Promise.resolve(
      new Response(JSON.stringify(route.body), {
        status: route.status,
        headers: { "content-type": "application/json" },
      })
    );
  });
  global.fetch = f as unknown as typeof fetch;
  return f;
}

const originalFetch = global.fetch;

beforeEach(() => {
  mockCart = makeCart();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("AddressStep", () => {
  it("renders saved addresses as cards and selecting one sets addressId and completes step 2", async () => {
    // GB is a region country since the Countries_breakdown work, so a complete saved
    // address carries state_region; without it the pick detours through the
    // complete-this-address panel (tested separately below).
    mockFetch({
      "GET /api/addresses": {
        status: 200,
        body: [
          {
            id: 1, label: "Home", first_name: "Ada", phone: "0700",
            line1: "1 Baker St", country_code: "GB", state_region: 11,
            city_text: "London", postcode: "NW1",
            is_default_shipping: true, is_default_billing: true,
          },
          {
            id: 2, label: "Office", first_name: "Ada", phone: "0700",
            line1: "2 Fleet St", country_code: "GB", state_region: 11,
            city_text: "London", postcode: "EC4",
            is_default_shipping: false, is_default_billing: false,
          },
        ],
      },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("2 Fleet St, London")).toBeInTheDocument());

    // The default (id 1) is preselected — visually checked — but nothing has
    // completed yet; only an explicit click advances the step.
    const homeCard = screen.getByText("1 Baker St, London").closest("[role='radio']")!;
    expect(homeCard).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("completed")).toHaveTextContent("");

    const officeCard = screen.getByText("2 Fleet St, London").closest("[role='radio']")!;
    fireEvent.click(officeCard);

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("2"));
    expect(screen.getByTestId("addressId")).toHaveTextContent("2");
    expect(screen.getByTestId("addressDisplay")).toHaveTextContent("2 Fleet St, London");
  });

  it("detours a saved GB address without a state through the complete-this-address panel", async () => {
    mockFetch({
      "GET /api/addresses": {
        status: 200,
        body: [
          {
            id: 3, label: "Home", first_name: "Ada", phone: "0700",
            line1: "1 Baker St", country_code: "GB", state_region: null,
            city_text: "London", postcode: "NW1",
            is_default_shipping: true, is_default_billing: true,
          },
        ],
      },
      "GET /api/regions?country=GB": {
        status: 200,
        body: [{ id: 11, name: "England", level: "state", has_children: false }],
      },
      "PATCH /api/addresses/3": {
        status: 200,
        body: {
          id: 3, label: "Home", first_name: "Ada", phone: "0700",
          line1: "1 Baker St", country_code: "GB", state_region: 11,
          city_text: "London", postcode: "NW1",
          is_default_shipping: true, is_default_billing: true,
        },
      },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("1 Baker St, London")).toBeInTheDocument());
    fireEvent.click(screen.getByText("1 Baker St, London").closest("[role='radio']")!);

    // The pick does NOT complete the step — the panel asks for the missing state.
    await waitFor(() => expect(screen.getByText(/complete this address/i)).toBeInTheDocument());
    expect(screen.getByTestId("completed")).toHaveTextContent("");

    await waitFor(() => expect(screen.getByRole("option", { name: "England" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^country$/i), { target: { value: "11" } });
    fireEvent.click(screen.getByRole("button", { name: /save and use this address/i }));

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("2"));
    expect(screen.getByTestId("addressId")).toHaveTextContent("3");
  });

  it("adds a new address (happy path): fills required fields, POSTs, selects it, and completes step 2", async () => {
    // GB renders BOTH the constituent-country select (bound to state_region) and the
    // city/postcode text fields since the Countries_breakdown work.
    mockFetch({
      "GET /api/addresses": { status: 200, body: [] },
      "GET /api/regions?country=GB": {
        status: 200,
        body: [{ id: 11, name: "England", level: "state", has_children: false }],
      },
      "POST /api/addresses": {
        status: 201,
        body: {
          id: 9, first_name: "Ada", phone: "07000000000", line1: "10 Downing St",
          country_code: "GB", state_region: 11, city_text: "London", postcode: "SW1A 2AA",
          is_default_shipping: false, is_default_billing: false,
        },
      },
    });

    renderHarness();

    // No saved addresses -> the add-new form opens directly.
    await waitFor(() => expect(screen.getByLabelText(/street address/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "07000000000" } });
    fireEvent.change(screen.getByLabelText(/street address/i), { target: { value: "10 Downing St" } });
    await waitFor(() => expect(screen.getByRole("option", { name: "England" })).toBeInTheDocument());
    // Two "Country" labels here: the locked cart-country input and RegionSelect's
    // constituent-country select — target the combobox.
    fireEvent.change(screen.getByRole("combobox", { name: /^country$/i }), {
      target: { value: "11" },
    });
    fireEvent.change(screen.getByLabelText(/^city\/town$/i), { target: { value: "London" } });
    fireEvent.change(screen.getByLabelText(/^postcode$/i), { target: { value: "SW1A 2AA" } });

    fireEvent.click(screen.getByRole("button", { name: /save address/i }));

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("2"));
    expect(screen.getByTestId("addressId")).toHaveTextContent("9");
    expect(screen.getByTestId("addressDisplay")).toHaveTextContent("10 Downing St, London");
  });

  it("shows a field error on a 400 create response and does not complete the step", async () => {
    mockFetch({
      "GET /api/addresses": { status: 200, body: [] },
      "POST /api/addresses": {
        status: 400,
        body: { postcode: ["This field is required for this country."] },
      },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByLabelText(/street address/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "07000000000" } });
    fireEvent.change(screen.getByLabelText(/street address/i), { target: { value: "10 Downing St" } });
    fireEvent.change(screen.getByLabelText(/^city\/town$/i), { target: { value: "London" } });

    fireEvent.click(screen.getByRole("button", { name: /save address/i }));

    await waitFor(() =>
      expect(screen.getByText(/required for this country/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/required for this country/i)).toHaveAttribute("role", "alert");
    expect(screen.getByTestId("completed")).toHaveTextContent("");
    expect(screen.getByTestId("addressId")).toHaveTextContent("");
  });

  it("opens the NG add-new form with a State/LGA RegionSelect instead of text fields", async () => {
    mockCart = makeCart({ country: "NG" });
    mockFetch({
      "GET /api/addresses": { status: 200, body: [] },
      "GET /api/regions?country=NG": {
        status: 200,
        body: [{ id: 1, name: "Lagos", level: "state", has_children: true }],
      },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByLabelText(/^state$/i)).toBeInTheDocument());
    expect(screen.queryByLabelText(/^city\/town$/i)).toBeNull();
    await waitFor(() => expect(screen.getByRole("option", { name: "Lagos" })).toBeInTheDocument());
  });

  it("NG pick sets the pin, mismatch nudges (never overrides), and the POST carries coordinates", async () => {
    mockCart = makeCart({ country: "NG" });
    const fetchMock = mockFetch({
      "GET /api/addresses": { status: 200, body: [] },
      "GET /api/regions?country=NG": {
        status: 200,
        body: [{ id: 1, name: "Lagos", level: "state", has_children: true }],
      },
      "GET /api/regions?parent=1": {
        status: 200,
        body: [
          { id: 2, name: "Ikeja", level: "area", has_children: false,
            latitude: "6.601800", longitude: "3.351000" },
          { id: 3, name: "Agege", level: "area", has_children: false,
            latitude: "6.625000", longitude: "3.320000" },
        ],
      },
      "POST /api/addresses": {
        status: 201,
        body: {
          id: 9, first_name: "Ada", phone: "08000000000", line1: "12 Allen Avenue",
          country_code: "NG", state_region: 1, area_region: 3,
          latitude: "6.601840", longitude: "3.351490",
          is_default_shipping: false, is_default_billing: false,
        },
      },
    });

    renderHarness();
    await waitFor(() => expect(screen.getByLabelText(/street address/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "08000000000" } });

    // Type → debounced suggestion → pick. The pick commits the pin.
    fireEvent.change(screen.getByLabelText(/street address/i), { target: { value: "12 Allen" } });
    fireEvent.click(await screen.findByText("12 Allen Avenue"));

    // Structured selection stays the source of truth: pick Lagos → Ikeja.
    await waitFor(() => expect(screen.getByRole("option", { name: "Lagos" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^state$/i), { target: { value: "1" } });
    await waitFor(() => expect(screen.getByRole("option", { name: "Ikeja" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^lga$/i), { target: { value: "2" } });

    // Google said Agege, the customer said Ikeja → a nudge, not an override.
    await waitFor(() => expect(screen.getByText(/Google places this address/i)).toBeInTheDocument());
    expect(screen.getByLabelText(/^lga$/i)).toHaveValue("2");
    fireEvent.click(screen.getByRole("button", { name: /use agege/i }));
    expect(screen.getByLabelText(/^lga$/i)).toHaveValue("3");

    fireEvent.click(screen.getByRole("button", { name: /save address/i }));
    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("2"));

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    const body = JSON.parse(post[1]!.body as string);
    expect(body.latitude).toBe("6.601840");
    expect(body.longitude).toBe("3.351490");
    expect(body.area_region).toBe(3);
  });

  // --- landmark (2026-08-28) ---------------------------------------------------------

  it("asks an NG shopper for a landmark, and puts it in the POST", async () => {
    // The field that gets a rider to the door. Rendered before the State, because that
    // is the order a Nigerian address is read in on the ground.
    mockCart = makeCart({ country: "NG" });
    const fetchMock = mockFetch({
      "GET /api/addresses": { status: 200, body: [] },
      "GET /api/regions?country=NG": {
        status: 200,
        body: [{ id: 1, name: "Lagos", level: "state", has_children: false }],
      },
      "POST /api/addresses": {
        status: 201,
        body: {
          id: 9, first_name: "Ada", phone: "08000000000", line1: "12 Allen Avenue",
          landmark: "Opposite Ikeja City Mall", country_code: "NG", state_region: 1,
          is_default_shipping: false, is_default_billing: false,
        },
      },
    });

    renderHarness();
    await waitFor(() => expect(screen.getByLabelText(/street address/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "08000000000" } });
    fireEvent.change(screen.getByLabelText(/street address/i), { target: { value: "12 Allen Avenue" } });
    fireEvent.change(screen.getByLabelText("Landmark"), {
      target: { value: "Opposite Ikeja City Mall" },
    });
    await waitFor(() => expect(screen.getByRole("option", { name: "Lagos" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^state$/i), { target: { value: "1" } });

    fireEvent.click(screen.getByRole("button", { name: /save address/i }));
    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("2"));

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(JSON.parse(post[1]!.body as string).landmark).toBe("Opposite Ikeja City Mall");
  });

  it("never shows a landmark box to a GB shopper", async () => {
    // Guards the decision, not just the code. A GB parcel routes on its postcode, and a
    // mandatory "nearest bus stop" would be a checkout blocker in a live market.
    mockCart = makeCart({ country: "GB" });
    mockFetch({
      "GET /api/addresses": { status: 200, body: [] },
      "GET /api/regions?country=GB": {
        status: 200,
        body: [{ id: 11, name: "England", level: "state", has_children: false }],
      },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByLabelText(/street address/i)).toBeInTheDocument());
    expect(screen.queryByLabelText("Landmark")).toBeNull();
    expect(screen.queryByRole("button", { name: "What is a landmark?" })).toBeNull();
    // The field it replaces for that market is still there.
    expect(screen.getByLabelText(/^postcode$/i)).toBeInTheDocument();
  });

  it("sends an empty landmark rather than omitting it, so the server owns the refusal", async () => {
    // If the client dropped the key, DRF would report "this field is required" for a
    // field the shopper was shown but whose value never left the browser — an error
    // they cannot act on. Sending "" makes the message land on the visible input.
    mockCart = makeCart({ country: "NG" });
    const fetchMock = mockFetch({
      "GET /api/addresses": { status: 200, body: [] },
      "GET /api/regions?country=NG": {
        status: 200,
        body: [{ id: 1, name: "Lagos", level: "state", has_children: false }],
      },
      "POST /api/addresses": {
        status: 400,
        body: { landmark: ["This field is required for this country."] },
      },
    });

    renderHarness();
    await waitFor(() => expect(screen.getByLabelText("Landmark")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "08000000000" } });
    fireEvent.change(screen.getByLabelText(/street address/i), { target: { value: "12 Allen Avenue" } });
    await waitFor(() => expect(screen.getByRole("option", { name: "Lagos" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^state$/i), { target: { value: "1" } });

    fireEvent.click(screen.getByRole("button", { name: /save address/i }));

    const post = await waitFor(() =>
      fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!,
    );
    expect(JSON.parse(post[1]!.body as string)).toHaveProperty("landmark", "");
    // And the server's complaint is shown against the field itself.
    expect(await screen.findByRole("alert")).toHaveTextContent(/required for this country/i);
  });
});
