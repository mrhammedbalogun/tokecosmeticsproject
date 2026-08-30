/**
 * The banner's behaviour, which is compliance rather than design.
 *
 * The assertions that matter here are the ones an audit would make: that a UK visitor is
 * asked before anything is stored, that "Reject all" is offered as prominently as
 * "Accept all", and that a refusal actually clears what was set.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ConsentBanner } from "@/components/consent/ConsentBanner";
import { ConsentProvider, useConsent } from "@/components/consent/ConsentProvider";
import type { MarketingConfig } from "@/lib/marketing";

const CONFIG: MarketingConfig = {
  tracking_enabled: true,
  consent_version: 1,
  consent_required_countries: ["GB", "IE", "DE"],
  channels: [{ code: "meta", pixel_id: "123", secondary_id: "" }],
};

function clearCookies() {
  for (const entry of document.cookie.split(";")) {
    const name = entry.split("=")[0].trim();
    if (name) document.cookie = `${name}=; path=/; max-age=0`;
  }
}

function setCountry(code: string) {
  document.cookie = `country=${code}; path=/`;
}

function readCookie(name: string): string {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : "";
}

/** Surfaces the context so a test can assert on the state, not just the pixels. */
function Probe() {
  const { consent, ready } = useConsent();
  return (
    <div data-testid="probe">
      {ready ? `${consent.marketing ? "m" : "-"}${consent.analytics ? "a" : "-"}` : "pending"}
    </div>
  );
}

function renderBanner(config: MarketingConfig = CONFIG) {
  return render(
    <ConsentProvider config={config}>
      <Probe />
      <ConsentBanner />
    </ConsentProvider>,
  );
}

beforeEach(() => {
  clearCookies();
  window.history.replaceState({}, "", "/");
});
afterEach(clearCookies);

describe("a UK visitor", () => {
  it("is asked before anything is granted", async () => {
    setCountry("GB");
    renderBanner();

    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("--"));
    expect(screen.getByRole("dialog", { name: /cookie choices/i })).toBeInTheDocument();
  });

  it("is offered Reject all as prominently as Accept all", () => {
    // Same element type, same row, neither disabled. A reject button that is harder to
    // find than accept is the dark pattern the ICO and the EDPB have both ruled against.
    setCountry("GB");
    renderBanner();

    const accept = screen.getByRole("button", { name: "Accept all" });
    const reject = screen.getByRole("button", { name: "Reject all" });
    expect(accept).toBeEnabled();
    expect(reject).toBeEnabled();
    expect(accept.parentElement).toBe(reject.parentElement);
  });
});

describe("a Nigerian visitor", () => {
  it("gets the opt-out regime, and is still shown the banner", async () => {
    setCountry("NG");
    renderBanner();

    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("ma"));
    // Implied is not chosen: the banner stays up until they answer.
    expect(screen.getByRole("dialog", { name: /cookie choices/i })).toBeInTheDocument();
  });
});

describe("answering", () => {
  it("stores the choice and puts the banner away", async () => {
    setCountry("GB");
    renderBanner();

    fireEvent.click(screen.getByRole("button", { name: "Accept all" }));

    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("ma"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(JSON.parse(readCookie("tc_consent"))).toEqual({ v: 1, a: 1, m: 1 });
  });

  it("lets the two categories be answered separately", async () => {
    setCountry("GB");
    renderBanner();

    fireEvent.click(screen.getByRole("button", { name: "Choose" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Measurement" }));
    fireEvent.click(screen.getByRole("button", { name: "Save my choices" }));

    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("-a"));
    expect(JSON.parse(readCookie("tc_consent"))).toEqual({ v: 1, a: 1, m: 0 });
  });
});

describe("a refusal", () => {
  it("clears the click ids and the vendors' own cookies", async () => {
    setCountry("NG");
    document.cookie = `tc_clk=${encodeURIComponent(JSON.stringify({ fbclid: "FB1" }))}; path=/`;
    document.cookie = "_fbp=fb.1.1.1; path=/";
    renderBanner();

    fireEvent.click(screen.getByRole("button", { name: "Reject all" }));

    await waitFor(() => expect(readCookie("tc_consent")).not.toBe(""));
    expect(readCookie("tc_clk")).toBe("");
    expect(readCookie("_fbp")).toBe("");
  });
});

describe("a fresh ad click", () => {
  it("is stored once an unanswered visitor accepts", async () => {
    // The proxy could not store it — no consent cookie existed on the landing request —
    // so the provider holds it and persists it on the grant.
    setCountry("GB");
    window.history.replaceState({}, "", "/?fbclid=FBCLICK");
    renderBanner();

    fireEvent.click(screen.getByRole("button", { name: "Accept all" }));

    await waitFor(() => expect(readCookie("tc_clk")).not.toBe(""));
    expect(JSON.parse(readCookie("tc_clk")).fbclid).toBe("FBCLICK");
  });

  it("is never stored if they refuse", async () => {
    setCountry("GB");
    window.history.replaceState({}, "", "/?fbclid=FBCLICK");
    renderBanner();

    fireEvent.click(screen.getByRole("button", { name: "Reject all" }));

    await waitFor(() => expect(readCookie("tc_consent")).not.toBe(""));
    expect(readCookie("tc_clk")).toBe("");
  });
});

describe("a shop that is measuring nothing", () => {
  it("asks nothing when tracking is on but no channel is configured", async () => {
    // The state Plan-44 SHIPPED in: every channel dark. No pixel loads and no server
    // event sends, so a banner would be friction on the funnel — and it would name five
    // platforms to a customer whose data none of them is receiving.
    setCountry("GB");
    renderBanner({ ...CONFIG, channels: [] });

    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("--"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("asks as soon as a channel is switched on", async () => {
    setCountry("GB");
    renderBanner();

    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: /cookie choices/i })).toBeInTheDocument(),
    );
  });
});

describe("the master switch", () => {
  it("asks nothing when the shop is not measuring anything", async () => {
    setCountry("GB");
    renderBanner({ ...CONFIG, tracking_enabled: false });

    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("--"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("a returning visitor", () => {
  it("is not asked again", async () => {
    setCountry("GB");
    document.cookie = `tc_consent=${encodeURIComponent(JSON.stringify({ v: 1, a: 1, m: 1 }))}; path=/`;
    renderBanner();

    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("ma"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("IS asked again when the consent version has moved", async () => {
    setCountry("GB");
    document.cookie = `tc_consent=${encodeURIComponent(JSON.stringify({ v: 1, a: 1, m: 1 }))}; path=/`;
    renderBanner({ ...CONFIG, consent_version: 2 });

    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: /cookie choices/i })).toBeInTheDocument(),
    );
    // And is back to denied in the meantime — they consented to the older list.
    expect(screen.getByTestId("probe")).toHaveTextContent("--");
  });
});
