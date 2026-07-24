import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import { SearchBar } from "@/components/layout/SearchBar";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

interface Deferred { promise: Promise<Response>; resolve: (r: Response) => void }
function deferred(): Deferred {
  let resolve!: (r: Response) => void;
  const promise = new Promise<Response>((r) => { resolve = r; });
  return { promise, resolve };
}
type Call = { url: string; init?: RequestInit } & Deferred;
let calls: Call[];

const jsonResponse = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });

beforeEach(() => {
  vi.useFakeTimers();
  push.mockClear();
  calls = [];
  global.fetch = vi.fn((url: string, init?: RequestInit) => {
    const d = deferred();
    calls.push({ url: String(url), init, ...d });
    return d.promise;
  }) as unknown as typeof fetch;
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

function type(value: string) {
  fireEvent.change(screen.getByRole("combobox"), { target: { value } });
}

describe("SearchBar autocomplete — stale-response safety", () => {
  it("does not let an out-of-order response overwrite fresh results", async () => {
    render(<SearchBar />);

    type("ra");
    await act(async () => { vi.advanceTimersByTime(300); });   // dispatch fetch A ("ra")
    type("rad");
    await act(async () => { vi.advanceTimersByTime(300); });   // dispatch fetch B ("rad")

    expect(calls).toHaveLength(2);
    expect(calls[0].url).toContain("q=ra");
    expect(calls[1].url).toContain("q=rad");

    // B (current) resolves first, then A (stale) resolves LATE.
    await act(async () => { calls[1].resolve(jsonResponse([{ name: "Radiance Glow Serum", slug: "radiance-glow-serum" }])); });
    await act(async () => { calls[0].resolve(jsonResponse([{ name: "Rambutan Balm", slug: "rambutan-balm" }])); });

    // The late "ra" response must NOT appear; only the current "rad" result shows.
    expect(screen.getByRole("option", { name: "Radiance Glow Serum" })).toBeInTheDocument();
    expect(screen.queryByText("Rambutan Balm")).not.toBeInTheDocument();
  });

  it("a late response cannot re-open the dropdown after the box is cleared", async () => {
    render(<SearchBar />);

    type("rad");
    await act(async () => { vi.advanceTimersByTime(300); });   // dispatch fetch A ("rad")
    type("");                                                  // clear fast (aborts A, closes list)

    await act(async () => { calls[0].resolve(jsonResponse([{ name: "Radiance Glow Serum", slug: "radiance-glow-serum" }])); });

    // No listbox — the stale response was gated out.
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    const input = screen.getByRole("combobox");
    expect(input.getAttribute("aria-expanded")).toBe("false");
  });
});
