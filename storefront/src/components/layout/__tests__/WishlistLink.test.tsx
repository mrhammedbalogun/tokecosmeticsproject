import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WishlistLink } from "@/components/layout/WishlistLink";

/** The header heart mounts on EVERY page, so its membership GET is the single most
 * repeated request an anonymous visitor makes. Signed out, that GET can only answer
 * 401 (the BFF route refuses before it reaches Django), so it is skipped — these
 * tests pin BOTH halves: no request when signed out, and the real saves when not. */

function renderLink(signedIn: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <WishlistLink signedIn={signedIn} />
    </QueryClientProvider>,
  );
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("WishlistLink", () => {
  it("makes NO /api/wishlist request when the visitor is signed out", async () => {
    renderLink(false);
    // The link still renders — appearance is unchanged for anonymous visitors.
    expect(screen.getByRole("link", { name: "Wishlist" })).toBeInTheDocument();
    // Give a stray effect a chance to fire before asserting the absence.
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows no saved-items dot when signed out, without asking the server", async () => {
    renderLink(false);
    // The dot is the ONLY thing the query fed, and its absence is what a 401 produced
    // before — so skipping the request cannot change what an anonymous visitor sees.
    expect(screen.queryByRole("link", { name: "Wishlist (has saved items)" })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("still fetches, and marks saved items, when the visitor IS signed in", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => [{ sku: "TOKE-1" }],
    });
    renderLink(true);
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Wishlist (has saved items)" })).toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenCalledWith("/api/wishlist");
  });

  it("falls back to the plain label when a signed-in shopper has saved nothing", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => [] });
    renderLink(true);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.getByRole("link", { name: "Wishlist" })).toBeInTheDocument();
  });
});
