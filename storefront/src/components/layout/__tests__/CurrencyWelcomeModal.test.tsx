import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import { CurrencyWelcomeModal } from "@/components/layout/CurrencyWelcomeModal";
import { GEO_DISMISS_KEY } from "@/lib/geo";

const refresh = vi.fn();
let pathname = "/";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
  usePathname: () => pathname,
}));

/** The popup reveals itself 700ms after mount (client-only, localStorage-gated). */
function renderAndReveal(ui: React.ReactElement) {
  const result = render(ui);
  act(() => vi.advanceTimersByTime(700));
  return result;
}

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  pathname = "/";
  refresh.mockClear();
});
afterEach(() => vi.useRealTimers());

describe("CurrencyWelcomeModal", () => {
  it("confirms the auto-set currency when geo matches the seeded market", () => {
    renderAndReveal(<CurrencyWelcomeModal currentCountry="CA" geoCountry="CA" />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/shopping in Canadian Dollars/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue shopping" })).toBeInTheDocument();
  });

  it("offers a switch when the cookie disagrees with geo", () => {
    renderAndReveal(<CurrencyWelcomeModal currentCountry="NG" geoCountry="CA" />);
    expect(screen.getByText(/Shop in Canadian Dollars\?/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Switch to CAD" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /keep NGN/i })).toBeInTheDocument();
  });

  it("renders nothing before the reveal delay elapses", () => {
    render(<CurrencyWelcomeModal currentCountry="CA" geoCountry="CA" />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders nothing for the NG home market", () => {
    renderAndReveal(<CurrencyWelcomeModal currentCountry="NG" geoCountry="NG" />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders nothing without a geo hint (local dev, geo unavailable)", () => {
    renderAndReveal(<CurrencyWelcomeModal currentCountry="NG" geoCountry="" />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders nothing once dismissed in this browser", () => {
    localStorage.setItem(GEO_DISMISS_KEY, "1");
    renderAndReveal(<CurrencyWelcomeModal currentCountry="CA" geoCountry="CA" />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("never interrupts checkout", () => {
    pathname = "/checkout";
    renderAndReveal(<CurrencyWelcomeModal currentCountry="CA" geoCountry="CA" />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Continue shopping dismisses for good", () => {
    renderAndReveal(<CurrencyWelcomeModal currentCountry="CA" geoCountry="CA" />);
    fireEvent.click(screen.getByRole("button", { name: "Continue shopping" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(localStorage.getItem(GEO_DISMISS_KEY)).toBe("1");
  });

  it("Escape dismisses for good", () => {
    renderAndReveal(<CurrencyWelcomeModal currentCountry="CA" geoCountry="CA" />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(localStorage.getItem(GEO_DISMISS_KEY)).toBe("1");
  });

  it("Change country reveals the market list with the current market ticked", () => {
    renderAndReveal(<CurrencyWelcomeModal currentCountry="CA" geoCountry="CA" />);
    fireEvent.click(screen.getByRole("button", { name: "Change country or currency" }));
    expect(screen.getByText("Choose your country")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /United Kingdom/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Canada.*Current selection/ })).toBeInTheDocument();
  });

  it("switching posts the market and refreshes prices", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    renderAndReveal(<CurrencyWelcomeModal currentCountry="NG" geoCountry="CA" />);
    fireEvent.click(screen.getByRole("button", { name: "Switch to CAD" }));
    // Let the transition's async body (fetch -> dismiss -> refresh) settle.
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/country",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ code: "CA" }) }),
    );
    expect(localStorage.getItem(GEO_DISMISS_KEY)).toBe("1");
    expect(refresh).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
