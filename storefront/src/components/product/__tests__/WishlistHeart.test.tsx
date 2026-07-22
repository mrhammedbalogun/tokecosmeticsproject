import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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

function mockFetchOnce(res: Response | Promise<Response> | (() => Promise<Response>)) {
  const impl = typeof res === "function" ? res : () => Promise.resolve(res as Response);
  const f = vi.fn(impl);
  global.fetch = f as unknown as typeof fetch;
  return f;
}
const ok = (status: number, body: unknown = {}) =>
  new Response(status === 204 ? null : JSON.stringify(body), { status });

describe("WishlistHeart", () => {
  it("renders nothing without a sku", () => {
    render(<WishlistHeart sku={null} name="Glow Serum" />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("optimistically marks the item saved and POSTs the sku", async () => {
    const f = mockFetchOnce(ok(201, { sku: "TOKE-X" }));
    render(<WishlistHeart sku="TOKE-X" name="Glow Serum" />);
    const btn = screen.getByRole("button");
    expect(btn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(btn);
    await waitFor(() => expect(btn).toHaveAttribute("aria-pressed", "true"));
    expect(f).toHaveBeenCalledWith("/api/wishlist", expect.objectContaining({ method: "POST" }));
  });

  it("rolls back the optimistic update when the response is not ok", async () => {
    const f = mockFetchOnce(ok(400, { detail: "dup" }));
    render(<WishlistHeart sku="TOKE-X" name="Glow Serum" />);
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    // without rollback the heart would stay pressed; assert it returns to false
    await waitFor(() => expect(f).toHaveBeenCalled());
    await waitFor(() => expect(btn).toHaveAttribute("aria-pressed", "false"));
    expect(push).not.toHaveBeenCalled();
  });

  it("rolls back when fetch itself rejects (offline / network error)", async () => {
    const f = mockFetchOnce(() => Promise.reject(new Error("network down")));
    render(<WishlistHeart sku="TOKE-X" name="Glow Serum" />);
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    await waitFor(() => expect(f).toHaveBeenCalled());
    await waitFor(() => expect(btn).toHaveAttribute("aria-pressed", "false"));
    // button re-enabled after the failure (pending cleared in finally)
    await waitFor(() => expect(btn).not.toBeDisabled());
  });

  it("sends unauthenticated users to /login and rolls back", async () => {
    mockFetchOnce(ok(401, { detail: "Not authenticated." }));
    render(<WishlistHeart sku="TOKE-X" name="Glow Serum" />);
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
    expect(btn).toHaveAttribute("aria-pressed", "false");
  });

  it("ignores a second click while a request is in flight (no POST/DELETE race)", async () => {
    let resolve!: (r: Response) => void;
    const pending = new Promise<Response>((r) => (resolve = r));
    const f = mockFetchOnce(() => pending);
    render(<WishlistHeart sku="TOKE-X" name="Glow Serum" />);
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    fireEvent.click(btn); // dropped by the in-flight guard
    expect(f).toHaveBeenCalledTimes(1);
    resolve(ok(201, { sku: "TOKE-X" }));
    await waitFor(() => expect(btn).not.toBeDisabled());
  });
});
