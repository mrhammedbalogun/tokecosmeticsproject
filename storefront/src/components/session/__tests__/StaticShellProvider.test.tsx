import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StaticShellProvider } from "@/components/session/StaticShellProvider";
import { useCartMayExist, useHasSession } from "@/components/session/SessionProvider";
import { AccountMenu } from "@/components/layout/AccountMenu";

/**
 * The client half of a prerendered shop page (Task 12D).
 *
 * These pages cannot resolve session or market on the server, so the guarantees Tasks 5
 * and 6 bought — an anonymous visitor makes neither the doomed wishlist GET nor the cart
 * GET that mints a row — have to survive being answered a beat later. That is what this
 * file pins.
 */

function Probe() {
  const signedIn = useHasSession();
  const cartMayExist = useCartMayExist();
  return (
    <>
      <span data-testid="session">{String(signedIn)}</span>
      <span data-testid="cart">{String(cartMayExist)}</span>
    </>
  );
}

const wrap = (ui: React.ReactNode) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
);

const shell = (body: unknown) =>
  vi.fn().mockResolvedValue({ ok: true, json: async () => body });

afterEach(() => { vi.unstubAllGlobals(); });

describe("StaticShellProvider", () => {
  it("STARTS SHUT — never 'unknown' — so the Task 5/6 gates cannot leak a request", async () => {
    // The whole point. `null` would mean "nobody told me", and every consumer falls back
    // to fetching on that — so publishing it for even one tick would fire the wishlist
    // GET that can only 401 and the cart GET that mints a cart, which is exactly what
    // those two tasks removed. React Query fires on mount; there is no second chance.
    let resolve!: (v: unknown) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise((r) => { resolve = r; })));

    render(wrap(<StaticShellProvider><Probe /></StaticShellProvider>));

    expect(screen.getByTestId("session").textContent).toBe("false");
    expect(screen.getByTestId("cart").textContent).toBe("false");
    resolve({ ok: true, json: async () => ({ signedIn: false, hasGuestCart: false, announcements: [] }) });
  });

  it("opens the gates once the shell answers for a signed-in shopper", async () => {
    vi.stubGlobal("fetch", shell({ signedIn: true, hasGuestCart: false, announcements: [] }));

    render(wrap(<StaticShellProvider><Probe /></StaticShellProvider>));

    await waitFor(() => expect(screen.getByTestId("session").textContent).toBe("true"));
    // Signed in counts on its own: an account can hold a cart built on another device.
    expect(screen.getByTestId("cart").textContent).toBe("true");
  });

  it("opens only the CART gate for an anonymous visitor who already has one", async () => {
    vi.stubGlobal("fetch", shell({ signedIn: false, hasGuestCart: true, announcements: [] }));

    render(wrap(<StaticShellProvider><Probe /></StaticShellProvider>));

    await waitFor(() => expect(screen.getByTestId("cart").textContent).toBe("true"));
    expect(screen.getByTestId("session").textContent).toBe("false");
  });

  it("a FAILED shell fetch leaves the gates shut rather than opening them", async () => {
    // Degraded, never broken: the page is still readable, and a network problem must not
    // turn into a burst of requests that were only ever going to be refused.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    render(wrap(<StaticShellProvider><Probe /></StaticShellProvider>));

    await waitFor(() => expect(screen.getByTestId("session").textContent).toBe("false"));
    expect(screen.getByTestId("cart").textContent).toBe("false");
  });

  it("asks the server exactly ONCE for all three values", async () => {
    // A static page trades a server RENDER for a server CALL. Three calls and the trade
    // stops paying — hence one `/api/shell` rather than an endpoint per value.
    const fetchMock = shell({ signedIn: false, hasGuestCart: false, announcements: [] });
    vi.stubGlobal("fetch", fetchMock);

    render(wrap(<StaticShellProvider><Probe /></StaticShellProvider>));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/shell");
  });

  it("renders the announcement bar EMPTY until the country-resolved strips arrive", async () => {
    // The bar's fallback names Nigeria. This HTML is served to every market, so it may
    // not carry that sentence — the strip shows its own height and nothing else.
    let resolve!: (v: unknown) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise((r) => { resolve = r; })));

    const { container } = render(wrap(<StaticShellProvider><span /></StaticShellProvider>));

    expect(container.textContent).not.toMatch(/Free delivery in Nigeria/);
    // The bar itself is present, so filling it shifts nothing.
    expect(container.querySelector(".announce-marquee")).not.toBeNull();

    resolve({ ok: true, json: async () => ({
      signedIn: false, hasGuestCart: false,
      announcements: [{ text: "Free delivery to the UK on all orders", url: "" }],
    }) });
    await waitFor(() =>
      expect(container.textContent).toMatch(/Free delivery to the UK on all orders/));
  });
});

describe("AccountMenu on a prerendered page", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", shell({ signedIn: true, hasGuestCart: false, announcements: [] }));
  });

  it("shows the signed-OUT control in the shared HTML, then corrects itself", async () => {
    // The static HTML is one file served to everybody, so it cannot know. Signed-out is
    // the safe default: it reveals nothing about any visitor, and it self-corrects. A
    // blank placeholder would not self-correct if the fetch failed, and would shift the
    // header when it landed.
    render(wrap(<StaticShellProvider><AccountMenu /></StaticShellProvider>));

    expect(screen.getByText("Sign in")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Account")).toBeInTheDocument());
    expect(screen.queryByText("Sign in")).toBeNull();
  });

  it("an explicit prop still wins, so the DYNAMIC header renders with no flicker", async () => {
    // `(shop)` resolves this server-side and passes it down; that path must not start
    // deferring to a context that will never be populated there.
    render(wrap(<AccountMenu signedIn />));
    expect(screen.getByText("Account")).toBeInTheDocument();
  });
});
