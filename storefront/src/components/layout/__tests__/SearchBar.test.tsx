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

describe("SearchBar autocomplete — bundles vs products", () => {
  it("sends a combo suggestion to /combo and a product to /product", async () => {
    render(<SearchBar />);
    type("glow");
    await act(async () => { vi.advanceTimersByTime(300); });
    await act(async () => {
      calls[0].resolve(jsonResponse([
        { name: "Glow Kit", slug: "glow-kit", type: "combo" },
        { name: "Glow Serum", slug: "glow-serum", type: "product" },
      ]));
    });

    // The bundle is LABELLED, not distinguished by position alone: the row behaves
    // differently once clicked and the shopper should know before they click it.
    expect(screen.getByText("Bundle")).toBeInTheDocument();

    // The bug this exists to stop: /product/glow-kit, which 404s — the two slug
    // namespaces are separate. (One click only: the dropdown closes on selection.)
    fireEvent.click(screen.getByRole("option", { name: /Glow Kit/ }).querySelector("button")!);
    expect(push).toHaveBeenCalledWith("/combo/glow-kit");
  });

  it("sends a product suggestion to /product", async () => {
    render(<SearchBar />);
    type("glow");
    await act(async () => { vi.advanceTimersByTime(300); });
    await act(async () => {
      calls[0].resolve(jsonResponse([{ name: "Glow Serum", slug: "glow-serum", type: "product" }]));
    });
    fireEvent.click(screen.getByRole("option", { name: /Glow Serum/ }).querySelector("button")!);
    expect(push).toHaveBeenCalledWith("/product/glow-serum");
  });

  it("treats a suggestion with no type as a product (payload from an older API)", async () => {
    render(<SearchBar />);
    type("glow");
    await act(async () => { vi.advanceTimersByTime(300); });
    await act(async () => {
      calls[0].resolve(jsonResponse([{ name: "Glow Serum", slug: "glow-serum" }]));
    });
    fireEvent.click(screen.getByRole("option", { name: /Glow Serum/ }).querySelector("button")!);
    expect(push).toHaveBeenCalledWith("/product/glow-serum");
  });

  it("keeps a combo and a product that share a slug as two separate rows", async () => {
    render(<SearchBar />);
    type("glow");
    await act(async () => { vi.advanceTimersByTime(300); });
    await act(async () => {
      calls[0].resolve(jsonResponse([
        { name: "Glow Kit", slug: "glow", type: "combo" },
        { name: "Glow Serum", slug: "glow", type: "product" },
      ]));
    });
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });
});
