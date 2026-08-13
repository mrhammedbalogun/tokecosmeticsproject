import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WishlistHeart } from "@/components/product/WishlistHeart";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const originalFetch = global.fetch;
beforeEach(() => {
  push.mockClear();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

const ok = (status: number, body: unknown = {}) =>
  new Response(status === 204 ? null : JSON.stringify(body), { status });

/** Route fetches: GET /api/wishlist answers the hook's membership query (`list`);
 * everything else (POST/DELETE toggles) answers with `mutation`. Returns a spy
 * that saw only the mutation calls. */
function mockWishlistFetch({
  list = () => Promise.resolve(ok(200, [])),
  mutation = () => Promise.resolve(ok(201, {})),
}: {
  list?: () => Promise<Response>;
  mutation?: () => Promise<Response>;
} = {}) {
  const mutationSpy = vi.fn((_url: RequestInfo | URL, _init?: RequestInit) => mutation());
  global.fetch = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (method === "GET" && String(url) === "/api/wishlist") return list();
    return mutationSpy(url, init);
  }) as unknown as typeof fetch;
  return mutationSpy;
}

function renderHeart(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("WishlistHeart", () => {
  it("renders nothing without a sku", () => {
    mockWishlistFetch();
    renderHeart(<WishlistHeart sku={null} name="Glow Serum" />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("optimistically marks the item saved and POSTs the sku", async () => {
    const f = mockWishlistFetch();
    renderHeart(<WishlistHeart sku="TOKE-X" name="Glow Serum" />);
    const btn = screen.getByRole("button");
    expect(btn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(btn);
    await waitFor(() => expect(btn).toHaveAttribute("aria-pressed", "true"));
    expect(f).toHaveBeenCalledWith("/api/wishlist", expect.objectContaining({ method: "POST" }));
  });

  it("shows saved on first paint when the sku is already wishlisted", async () => {
    mockWishlistFetch({ list: () => Promise.resolve(ok(200, [{ sku: "TOKE-X" }])) });
    renderHeart(<WishlistHeart sku="TOKE-X" name="Glow Serum" />);
    await waitFor(() =>
      expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"),
    );
  });

  it("rolls back the optimistic update when the response is not ok", async () => {
    const f = mockWishlistFetch({ mutation: () => Promise.resolve(ok(400, { detail: "dup" })) });
    renderHeart(<WishlistHeart sku="TOKE-X" name="Glow Serum" />);
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    // without rollback the heart would stay pressed; assert it returns to false
    await waitFor(() => expect(f).toHaveBeenCalled());
    await waitFor(() => expect(btn).toHaveAttribute("aria-pressed", "false"));
    expect(push).not.toHaveBeenCalled();
  });

  it("rolls back when fetch itself rejects (offline / network error)", async () => {
    const f = mockWishlistFetch({ mutation: () => Promise.reject(new Error("network down")) });
    renderHeart(<WishlistHeart sku="TOKE-X" name="Glow Serum" />);
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    await waitFor(() => expect(f).toHaveBeenCalled());
    await waitFor(() => expect(btn).toHaveAttribute("aria-pressed", "false"));
    // button re-enabled after the failure
    await waitFor(() => expect(btn).not.toBeDisabled());
  });

  it("sends unauthenticated users to /login and rolls back", async () => {
    mockWishlistFetch({
      list: () => Promise.resolve(ok(401, { detail: "Not authenticated." })),
      mutation: () => Promise.resolve(ok(401, { detail: "Not authenticated." })),
    });
    renderHeart(<WishlistHeart sku="TOKE-X" name="Glow Serum" />);
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
    await waitFor(() => expect(btn).toHaveAttribute("aria-pressed", "false"));
  });

  it("ignores a second click while a request is in flight (no POST/DELETE race)", async () => {
    let resolve!: (r: Response) => void;
    const pending = new Promise<Response>((r) => (resolve = r));
    const f = mockWishlistFetch({ mutation: () => pending });
    renderHeart(<WishlistHeart sku="TOKE-X" name="Glow Serum" />);
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    fireEvent.click(btn); // dropped by the in-flight guard
    // the mutation fetch fires on a microtask (onMutate awaits first), so wait
    await waitFor(() => expect(f).toHaveBeenCalledTimes(1));
    resolve(ok(201, { sku: "TOKE-X" }));
    await waitFor(() => expect(btn).not.toBeDisabled());
    expect(f).toHaveBeenCalledTimes(1); // still one — the second click never fired
  });
});
