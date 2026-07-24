import { useState } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RegionSelect } from "@/components/checkout/RegionSelect";

/** RegionSelect is fully controlled (it emits ids via onChange but tracks none of
 * its own) — this thin wrapper feeds state_region/area_region back in as props,
 * the way AddressStep's `form` state does, so a state pick is reflected on the
 * next render before an area pick happens. */
function ControlledHarness({
  country,
  onChange,
}: {
  country: string;
  onChange: (v: { state_region?: number; area_region?: number }) => void;
}) {
  const [state, setState] = useState<{ state_region?: number; area_region?: number }>({});
  return (
    <RegionSelect
      country={country}
      stateValue={state.state_region}
      areaValue={state.area_region}
      onChange={(v) => {
        setState(v);
        onChange(v);
      }}
    />
  );
}

type Route = { status: number; body: unknown };

function mockFetch(routes: Record<string, Route>) {
  const f = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const route = routes[url];
    if (!route) return Promise.reject(new Error(`unexpected fetch: ${url}`));
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
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("RegionSelect", () => {
  it("loads states for the country on mount, then loads LGAs when a state is picked", async () => {
    mockFetch({
      "/api/regions?country=NG": {
        status: 200,
        body: [{ id: 1, name: "Lagos", level: "state", has_children: true }],
      },
      "/api/regions?parent=1": {
        status: 200,
        body: [{ id: 11, name: "Ikeja", level: "area", has_children: false }],
      },
    });

    const onChange = vi.fn();
    render(<ControlledHarness country="NG" onChange={onChange} />);

    await waitFor(() => expect(screen.getByRole("option", { name: "Lagos" })).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("State"), { target: { value: "1" } });

    expect(onChange).toHaveBeenCalledWith({ state_region: 1, area_region: undefined });
    await waitFor(() => expect(screen.getByRole("option", { name: "Ikeja" })).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("LGA"), { target: { value: "11" } });
    expect(onChange).toHaveBeenLastCalledWith({ state_region: 1, area_region: 11 });
  });

  it("renders a note instead of crashing when no regions are seeded for the country", async () => {
    mockFetch({
      "/api/regions?country=ZZ": { status: 200, body: [] },
    });

    render(<RegionSelect country="ZZ" onChange={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText(/no regions are set up/i)).toBeInTheDocument()
    );
  });
});
