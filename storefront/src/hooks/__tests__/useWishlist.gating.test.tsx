import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/components/session/SessionProvider";
import { WishlistLink } from "@/components/layout/WishlistLink";
import { WishlistHeart } from "@/components/product/WishlistHeart";
import { PdpWishlistButton } from "@/components/product/PdpWishlistButton";
import { PdpProvider } from "@/components/product/PdpContext";
import type { Variant } from "@/lib/catalog";

/**
 * The wishlist gate, end to end.
 *
 * `useWishlist` is called by the header heart, EVERY product card's heart and the PDP
 * save button, all sharing one ["wishlist","skus"] key — so one un-gated consumer makes
 * the request for the whole page. These tests pin both directions for each of them, and
 * the sharing itself, because that is the property the optimisation depends on.
 */

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true, json: async () => [{ sku: "TOKE-1" }] });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const VARIANTS = [
  { id: 1, sku: "TOKE-1", name: "50ml", option_values: {}, price: null, in_stock: true, low_stock: false },
] as unknown as Variant[];

function mount(signedIn: boolean, ui: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <SessionProvider signedIn={signedIn}>{ui}</SessionProvider>
    </QueryClientProvider>,
  );
}

const heart = <WishlistHeart sku="TOKE-1" name="Glow Serum" />;
const pdpButton = (
  <PdpProvider variants={VARIANTS}>
    <PdpWishlistButton name="Glow Serum" variants={VARIANTS} />
  </PdpProvider>
);

/** Nothing may reach /api/wishlist; a stray effect gets a tick to prove it. */
async function expectNoWishlistCall() {
  await new Promise((r) => setTimeout(r, 20));
  const calls = fetchMock.mock.calls.filter((c) => String(c[0]).includes("/api/wishlist"));
  expect(calls).toHaveLength(0);
}

describe("anonymous visitors make no wishlist request", () => {
  it("A. WishlistHeart (on every product card) does not query", async () => {
    mount(false, heart);
    expect(screen.getByRole("button", { name: /Save Glow Serum/ })).toBeInTheDocument();
    await expectNoWishlistCall();
  });

  it("B. PdpWishlistButton does not query", async () => {
    mount(false, pdpButton);
    await expectNoWishlistCall();
  });

  it("E. the header heart does not query, and still renders", async () => {
    mount(false, <WishlistLink />);
    expect(screen.getByRole("link", { name: "Wishlist" })).toBeInTheDocument();
    await expectNoWishlistCall();
  });

  it("a whole page's worth of consumers together still make no request", async () => {
    mount(false, <>{heart}{pdpButton}<WishlistLink /></>);
    await expectNoWishlistCall();
  });
});

describe("authenticated visitors keep the existing behaviour", () => {
  it("C. WishlistHeart queries and renders the saved state", async () => {
    mount(true, heart);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Remove Glow Serum/ })).toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenCalledWith("/api/wishlist");
  });

  it("D. PdpWishlistButton queries and reflects the saved state", async () => {
    mount(true, pdpButton);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/wishlist"));
    await waitFor(() => expect(screen.getByText(/Saved/i)).toBeInTheDocument());
  });

  it("E. the header heart queries and shows the dot", async () => {
    mount(true, <WishlistLink />);
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Wishlist (has saved items)" })).toBeInTheDocument(),
    );
  });

  it("2. three consumers share ONE ['wishlist','skus'] fetch (dedup intact)", async () => {
    mount(true, <>{heart}{pdpButton}<WishlistLink /></>);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 30));
    const calls = fetchMock.mock.calls.filter((c) => String(c[0]) === "/api/wishlist");
    expect(calls).toHaveLength(1);
  });
});

describe("backward compatibility and overrides", () => {
  it("with NO SessionProvider above it, the hook fetches exactly as it did before", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <WishlistLink />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/wishlist"));
  });

  it("an explicit enabled={false} beats a signed-in context", async () => {
    mount(true, <WishlistLink signedIn={false} />);
    await expectNoWishlistCall();
  });
});
