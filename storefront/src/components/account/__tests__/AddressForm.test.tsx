import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AddressForm } from "@/components/account/AddressForm";
import type { Address } from "@/components/checkout/address-fields";

type Route = { status: number; body: unknown };

/** Routes fetch calls by "METHOD url", same convention as AddressStep.test.tsx (GET and
 * POST both hit /api/addresses, so a URL-only map isn't enough). */
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

function lastCall(f: ReturnType<typeof mockFetch>) {
  const [input, init] = f.mock.calls[f.mock.calls.length - 1];
  return { url: String(input), init: init as RequestInit | undefined };
}

const GB_ADDRESS: Address = {
  id: 5, label: "Office", first_name: "Ada", last_name: "L", phone: "+447911123456",
  line1: "2 Fleet St", line2: "", country_code: "GB", city_text: "London",
  state_text: "", postcode: "EC4", is_default_shipping: false, is_default_billing: false,
};

const originalFetch = global.fetch;
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("AddressForm", () => {
  it("defaults to NG, shows a State select, and loads LGAs after a state is picked", async () => {
    mockFetch({
      "GET /api/regions?country=NG": {
        status: 200,
        body: [{ id: 1, name: "Lagos", level: "state", has_children: true }],
      },
      "GET /api/regions?parent=1": {
        status: 200,
        body: [{ id: 11, name: "Ikeja", level: "area", has_children: false }],
      },
    });

    render(<AddressForm onSaved={vi.fn()} onCancel={vi.fn()} />);

    await waitFor(() => expect(screen.getByLabelText(/^state$/i)).toBeInTheDocument());
    expect(screen.queryByLabelText(/^city\/town$/i)).toBeNull();
    await waitFor(() => expect(screen.getByRole("option", { name: "Lagos" })).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/^state$/i), { target: { value: "1" } });

    await waitFor(() => expect(screen.getByRole("option", { name: "Ikeja" })).toBeInTheDocument());
  });

  it("swaps country-specific fields on country change and clears stale values", async () => {
    mockFetch({
      "GET /api/regions?country=NG": { status: 200, body: [] },
      "GET /api/regions?country=GB": { status: 200, body: [] },
    });

    render(<AddressForm onSaved={vi.fn()} onCancel={vi.fn()} />);

    // NG by default -> regions branch (no seeded regions here -> the "no regions" message).
    await waitFor(() =>
      expect(screen.getByText(/no regions are set up/i)).toBeInTheDocument()
    );

    fireEvent.change(screen.getByLabelText(/^country$/i), { target: { value: "GB" } });

    // City/postcode text fields now render instead of the region message.
    await waitFor(() => expect(screen.getByLabelText(/^city\/town$/i)).toBeInTheDocument());
    expect(screen.getByLabelText(/^city\/town$/i)).toHaveValue("");
    expect(screen.getByLabelText(/^postcode$/i)).toHaveValue("");

    fireEvent.change(screen.getByLabelText(/^city\/town$/i), { target: { value: "London" } });
    expect(screen.getByLabelText(/^city\/town$/i)).toHaveValue("London");

    // Switching country again clears the value just typed for the old country.
    fireEvent.change(screen.getByLabelText(/^country$/i), { target: { value: "US" } });
    await waitFor(() => expect(screen.getByLabelText(/^city$/i)).toHaveValue(""));
  });

  it("renders a 400 field error beside its field on create", async () => {
    const f = mockFetch({
      "GET /api/regions?country=NG": { status: 200, body: [] },
      "POST /api/addresses": {
        status: 400,
        body: { line1: ["This field is required."] },
      },
    });

    render(<AddressForm onSaved={vi.fn()} onCancel={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText(/no regions are set up/i)).toBeInTheDocument()
    );
    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "+2348023900964" } });
    fireEvent.change(screen.getByLabelText(/street address/i), { target: { value: "x" } });

    fireEvent.click(screen.getByRole("button", { name: /save address/i }));

    await waitFor(() =>
      expect(screen.getByText("This field is required.")).toBeInTheDocument()
    );
    expect(screen.getByText("This field is required.")).toHaveAttribute("role", "alert");
    expect(f).toHaveBeenCalled();
  });

  it("POSTs the built payload on create and fires onSaved with the response", async () => {
    const created: Address = {
      id: 9, first_name: "Ada", phone: "07000000000", line1: "10 Downing St",
      line2: "", country_code: "GB", city_text: "London", state_text: "", postcode: "SW1A 2AA",
      is_default_shipping: false, is_default_billing: false,
    };
    const f = mockFetch({
      "GET /api/regions?country=NG": { status: 200, body: [] },
      "POST /api/addresses": { status: 201, body: created },
    });
    const onSaved = vi.fn();

    render(<AddressForm onSaved={onSaved} onCancel={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText(/no regions are set up/i)).toBeInTheDocument()
    );
    fireEvent.change(screen.getByLabelText(/^country$/i), { target: { value: "GB" } });
    await waitFor(() => expect(screen.getByLabelText(/^city\/town$/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "+447911123456" } });
    fireEvent.change(screen.getByLabelText(/street address/i), { target: { value: "10 Downing St" } });
    fireEvent.change(screen.getByLabelText(/^city\/town$/i), { target: { value: "London" } });
    fireEvent.change(screen.getByLabelText(/^postcode$/i), { target: { value: "SW1A 2AA" } });

    fireEvent.click(screen.getByRole("button", { name: /save address/i }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(created));

    const { url, init } = lastCall(f);
    expect(url).toBe("/api/addresses");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init!.body as string)).toEqual({
      country_code: "GB",
      line1: "10 Downing St",
      first_name: "Ada",
      phone: "+447911123456",
      city_text: "London",
      postcode: "SW1A 2AA",
    });
  });

  it("PATCHes the built payload on edit (prefilled from initial) and fires onSaved", async () => {
    const updated: Address = { ...GB_ADDRESS, line2: "Suite 4" };
    const f = mockFetch({
      "GET /api/regions?country=GB": { status: 200, body: [] },
      "PATCH /api/addresses/5": { status: 200, body: updated },
    });
    const onSaved = vi.fn();

    render(<AddressForm initial={GB_ADDRESS} onSaved={onSaved} onCancel={vi.fn()} />);

    expect(screen.getByLabelText(/street address/i)).toHaveValue("2 Fleet St");
    expect(screen.getByLabelText(/^city\/town$/i)).toHaveValue("London");

    fireEvent.change(screen.getByLabelText(/apartment, suite/i), { target: { value: "Suite 4" } });
    fireEvent.click(screen.getByRole("button", { name: /save address/i }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(updated));

    const { url, init } = lastCall(f);
    expect(url).toBe("/api/addresses/5");
    expect(init?.method).toBe("PATCH");
    const body = JSON.parse(init!.body as string);
    expect(body.line2).toBe("Suite 4");
    expect(body.line1).toBe("2 Fleet St");
  });

  // Fix-loop round 1: RegionSelect only fetches a state's LGAs from a user's state-select
  // click, never on mount — so editing a saved NG address rendered the LGA select blank
  // (no matching <option> for the saved area_region), and re-picking the same state to
  // "fix" it reset area_region to undefined, silently dropping the stored LGA on an
  // otherwise-unrelated save. AddressForm now prefetches the saved state's LGAs itself
  // (AccountRegionSelect) so the saved value renders selected from first paint.
  it("prefills the saved NG state and LGA on mount (edit mode) instead of rendering blank", async () => {
    const ngAddress: Address = {
      id: 7, first_name: "Ada", phone: "0700", line1: "12 Allen Ave",
      country_code: "NG", state_region: 1, area_region: 11,
      is_default_shipping: false, is_default_billing: false,
    };
    mockFetch({
      "GET /api/regions?country=NG": {
        status: 200,
        body: [{ id: 1, name: "Lagos", level: "state", has_children: true }],
      },
      "GET /api/regions?parent=1": {
        status: 200,
        body: [
          { id: 11, name: "Ikeja", level: "area", has_children: false },
          { id: 12, name: "Epe", level: "area", has_children: false },
        ],
      },
    });

    render(<AddressForm initial={ngAddress} onSaved={vi.fn()} onCancel={vi.fn()} />);

    await waitFor(() => expect(screen.getByLabelText(/^state$/i)).toHaveValue("1"));
    await waitFor(() => expect(screen.getByLabelText(/^lga$/i)).toHaveValue("11"));
  });

  it("keeps the saved LGA in the PATCH payload when only an unrelated field changes", async () => {
    const ngAddress: Address = {
      id: 7, first_name: "Ada", last_name: "L", phone: "+2348030000000", line1: "12 Allen Ave",
      country_code: "NG", state_region: 1, area_region: 11,
      is_default_shipping: false, is_default_billing: false,
    };
    const updated: Address = { ...ngAddress, phone: "+2348023900964" };
    const f = mockFetch({
      "GET /api/regions?country=NG": {
        status: 200,
        body: [{ id: 1, name: "Lagos", level: "state", has_children: true }],
      },
      "GET /api/regions?parent=1": {
        status: 200,
        body: [{ id: 11, name: "Ikeja", level: "area", has_children: false }],
      },
      "PATCH /api/addresses/7": { status: 200, body: updated },
    });
    const onSaved = vi.fn();

    render(<AddressForm initial={ngAddress} onSaved={onSaved} onCancel={vi.fn()} />);

    // Wait for the prefill to land before touching an unrelated field, otherwise the
    // assertion below would pass by accident (submitting before the fetch resolves).
    await waitFor(() => expect(screen.getByLabelText(/^lga$/i)).toHaveValue("11"));

    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "+2348023900964" } });
    fireEvent.click(screen.getByRole("button", { name: /save address/i }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(updated));

    const { url, init } = lastCall(f);
    expect(url).toBe("/api/addresses/7");
    const body = JSON.parse(init!.body as string);
    expect(body.state_region).toBe(1);
    expect(body.area_region).toBe(11);
    expect(body.phone).toBe("+2348023900964");
  });

  // Fix 2 (15d final review): under DRF partial update, an OMITTED field is left
  // unchanged — only an explicit "" clears it. The payload builder was copied from
  // checkout's create-only AddressStep, which omits empty optionals; on a PATCH that
  // means clearing label/line2 (etc.) in the edit form silently reverts on save. Edit
  // mode must send "" for a cleared optional field instead of dropping it.
  it("sends \"\" for cleared optional fields (label, line2) on a PATCH, not an omission", async () => {
    const updated: Address = { ...GB_ADDRESS, label: "", line2: "" };
    const f = mockFetch({
      "GET /api/regions?country=GB": { status: 200, body: [] },
      "PATCH /api/addresses/5": { status: 200, body: updated },
    });
    const onSaved = vi.fn();

    render(<AddressForm initial={GB_ADDRESS} onSaved={onSaved} onCancel={vi.fn()} />);

    expect(screen.getByLabelText(/label/i)).toHaveValue("Office");
    fireEvent.change(screen.getByLabelText(/label/i), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText(/apartment, suite/i), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /save address/i }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(updated));

    const { init: patchInit } = lastCall(f);
    const body = JSON.parse(patchInit!.body as string);
    expect(body.label).toBe("");
    expect(body.line2).toBe("");
  });

  it("still omits empty optional fields on create (POST payload unchanged)", async () => {
    const created: Address = {
      id: 10, first_name: "Ada", phone: "07000000000", line1: "10 Downing St",
      country_code: "GB", city_text: "London", postcode: "SW1A 2AA",
      is_default_shipping: false, is_default_billing: false,
    };
    const f = mockFetch({
      "GET /api/regions?country=NG": { status: 200, body: [] },
      "POST /api/addresses": { status: 201, body: created },
    });
    const onSaved = vi.fn();

    render(<AddressForm onSaved={onSaved} onCancel={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText(/no regions are set up/i)).toBeInTheDocument()
    );
    fireEvent.change(screen.getByLabelText(/^country$/i), { target: { value: "GB" } });
    await waitFor(() => expect(screen.getByLabelText(/^city\/town$/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "+447911123456" } });
    fireEvent.change(screen.getByLabelText(/street address/i), { target: { value: "10 Downing St" } });
    fireEvent.change(screen.getByLabelText(/^city\/town$/i), { target: { value: "London" } });
    fireEvent.change(screen.getByLabelText(/^postcode$/i), { target: { value: "SW1A 2AA" } });
    // label/line2/last_name left blank — must be OMITTED (not sent as "") on create.

    fireEvent.click(screen.getByRole("button", { name: /save address/i }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(created));

    const { url, init } = lastCall(f);
    expect(url).toBe("/api/addresses");
    const body = JSON.parse(init!.body as string);
    expect(body).not.toHaveProperty("label");
    expect(body).not.toHaveProperty("line2");
    expect(body).not.toHaveProperty("last_name");
  });

  it("prefills the saved pin in edit mode and keeps it in the PATCH (Plan-32b)", async () => {
    // No googleMaps mock on purpose: without a key the map degrades to its
    // fallback line, and the pin must still round-trip from the saved address.
    const pinned: Address = {
      id: 7, label: "Home", first_name: "Ada", phone: "+2348030000000", line1: "12 Allen Ave",
      line2: "", country_code: "NG", state_region: 1, area_region: 11,
      latitude: "6.601840", longitude: "3.351490",
      is_default_shipping: false, is_default_billing: false,
    };
    const f = mockFetch({
      "GET /api/regions?country=NG": {
        status: 200,
        body: [{ id: 1, name: "Lagos", level: "state", has_children: true }],
      },
      "GET /api/regions?parent=1": {
        status: 200,
        body: [{ id: 11, name: "Ikeja", level: "area", has_children: false,
                 latitude: "6.601800", longitude: "3.351000" }],
      },
      "PATCH /api/addresses/7": { status: 200, body: pinned },
    });
    const onSaved = vi.fn();
    render(<AddressForm initial={pinned} onSaved={onSaved} onCancel={vi.fn()} />);

    // The pin renders its map section (fallback copy, since no key in tests).
    await waitFor(() =>
      expect(screen.getByText(/map could not load/i)).toBeInTheDocument()
    );

    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "+2348023900964" } });
    fireEvent.click(screen.getByRole("button", { name: /save address/i }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());

    const body = JSON.parse(lastCall(f).init!.body as string);
    expect(body.latitude).toBe("6.601840");
    expect(body.longitude).toBe("3.351490");
  });
});
