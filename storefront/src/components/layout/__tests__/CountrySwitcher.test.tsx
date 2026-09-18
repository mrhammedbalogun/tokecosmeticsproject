import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CountrySwitcher } from "@/components/layout/CountrySwitcher";
import type { Market } from "@/lib/country";

// A STABLE refresh mock, not a fresh `vi.fn()` per call. The old inline factory made the
// function unassertable: every `useRouter()` handed back a different spy, so nothing could
// check whether the component had actually called it — which is the one thing the market
// switch depends on. See the last test in this file.
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

const markets: Market[] = [
  { code: "NG", name: "Nigeria", currency: { code: "NGN", symbol: "₦", decimal_places: 2 }, is_default: true, is_rest_of_world: false, area_label: "LGA" },
  { code: "CA", name: "Canada", currency: { code: "CAD", symbol: "CA$", decimal_places: 2 }, is_default: false, is_rest_of_world: false, area_label: "Municipality" },
];

describe("CountrySwitcher", () => {
  it("shows the current market", () => {
    render(<CountrySwitcher markets={markets} current="CA" />);
    expect(screen.getByRole("combobox")).toHaveValue("CA");
  });

  it("follows a country change made elsewhere (welcome popup) on refresh re-render", () => {
    // The bug: useState(current) froze the mount value, so after the popup switched the
    // cookie and router.refresh()ed, prices updated but this select stayed on the old
    // market until a hard reload. The re-render with a new `current` must win.
    const { rerender } = render(<CountrySwitcher markets={markets} current="CA" />);
    rerender(<CountrySwitcher markets={markets} current="NG" />);
    expect(screen.getByRole("combobox")).toHaveValue("NG");
  });

  it("never prints the currency twice for the rest-of-world market", () => {
    /**
     * Every caller renders `labelFor(m) — m.currency.code`, and `labelFor` used to return
     * "International (USD)", so the option read "International (USD) — USD". That was not
     * only sloppy: it was the LONGEST option in the list, and a native <select> sizes
     * itself to its longest option, so those extra characters were part of what made this
     * control 198px wide and pushed the cart button off a 390px phone.
     */
    render(
      <CountrySwitcher
        markets={[{
          code: "ZZ", name: "Rest of world", is_default: false, is_rest_of_world: true,
          area_label: "Region", currency: { code: "USD", symbol: "$", decimal_places: 2 },
        }]}
        current="ZZ"
      />,
    );
    expect(screen.getByRole("option").textContent).toBe("International — USD");
  });

  it("accepts a className so the header can gate it to lg and the drawer can fill a row", () => {
    // The header renders it `hidden … lg:flex`; if this prop stops being applied the
    // 198px select returns to a phone header, which is the whole bug.
    const { container } = render(
      <CountrySwitcher markets={markets} current="NG" className="hidden lg:flex" />,
    );
    expect(container.querySelector("label")?.className).toBe("hidden lg:flex");
  });
});

/**
 * THE MARKET-SWITCH CONTRACT (baselined in Task 12B, 2026-09-16).
 *
 * Prices, stock, banners and delivery copy are all resolved SERVER-SIDE from the `country`
 * cookie. So switching market is two steps that only work together:
 *
 *     POST /api/country   writes the cookie
 *     router.refresh()    re-runs the Server Components, which re-read it
 *
 * Drop the refresh and the cookie changes while every price on screen stays in the old
 * currency until a hard reload — the shop would claim to be in CAD and quote naira.
 *
 * This is pinned NOW, before any static/ISR work, because `router.refresh()` is exactly
 * what a statically rendered route cannot honour: a prerendered page has no Server
 * Component left to re-run, so it would return the same cached HTML and the switch would
 * silently stop working. Whoever changes the rendering mode has to come here and replace
 * this contract deliberately (market in the URL, or client-rendered prices) rather than
 * discover it from a customer report.
 */
describe("switching market refreshes the server-rendered prices", () => {
  beforeEach(() => {
    refresh.mockClear();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    localStorage.clear();
  });

  it("writes the cookie via POST /api/country AND refreshes the server render", async () => {
    render(<CountrySwitcher markets={markets} current="NG" />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "CA" } });

    await waitFor(() => expect(refresh).toHaveBeenCalled());

    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/country");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ code: "CA" });
  });

  it("REFRESHES AFTER the cookie is written, never before", async () => {
    // Ordering is the whole contract. Refreshing first re-renders the server with the OLD
    // cookie, so the prices come back unchanged and the bug looks like "the switcher does
    // nothing" rather than "the calls are in the wrong order".
    const order: string[] = [];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => {
      order.push("cookie-write");
      return { ok: true };
    }));
    refresh.mockImplementation(() => { order.push("refresh"); });

    render(<CountrySwitcher markets={markets} current="NG" />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "CA" } });

    await waitFor(() => expect(order).toEqual(["cookie-write", "refresh"]));
  });
});
