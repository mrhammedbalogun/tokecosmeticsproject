/**
 * Which scripts are emitted, for whom.
 *
 * `next/script` is mocked down to a plain tag carrying its id, because what is under
 * test is the GATE, not Next's loader. The gate is the part with consequences: a pixel
 * emitted for a visitor who declined is the failure this whole plan exists to prevent,
 * and it would look identical to a working integration from the outside.
 */
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConsentProvider } from "@/components/consent/ConsentProvider";
import { TrackingScripts } from "@/components/consent/TrackingScripts";
import type { MarketingConfig } from "@/lib/marketing";

vi.mock("next/script", () => ({
  default: ({ id, src, children }: { id?: string; src?: string; children?: string }) => (
    <script data-testid={id} data-src={src}>
      {children}
    </script>
  ),
}));

const ALL_CHANNELS: MarketingConfig = {
  tracking_enabled: true,
  consent_version: 1,
  consent_required_countries: ["GB"],
  channels: [
    { code: "meta", pixel_id: "META123", secondary_id: "" },
    { code: "tiktok", pixel_id: "TT123", secondary_id: "" },
    { code: "snapchat", pixel_id: "SNAP123", secondary_id: "" },
    { code: "ga4", pixel_id: "G-123", secondary_id: "" },
    { code: "google_ads", pixel_id: "AW-123", secondary_id: "LABEL" },
  ],
};

function clearCookies() {
  for (const entry of document.cookie.split(";")) {
    const name = entry.split("=")[0].trim();
    if (name) document.cookie = `${name}=; path=/; max-age=0`;
  }
}

function renderScripts(config = ALL_CHANNELS) {
  return render(
    <ConsentProvider config={config}>
      <TrackingScripts config={config} />
    </ConsentProvider>,
  );
}

function consentCookie(marketing: number, analytics: number) {
  document.cookie = `tc_consent=${encodeURIComponent(
    JSON.stringify({ v: 1, a: analytics, m: marketing }),
  )}; path=/`;
}

beforeEach(clearCookies);

describe("a visitor who refused", () => {
  beforeEach(() => {
    document.cookie = "country=GB; path=/";
    consentCookie(0, 0);
  });

  it("gets no Meta, TikTok or Snapchat pixel at all", () => {
    const { queryByTestId } = renderScripts();
    expect(queryByTestId("meta-pixel")).toBeNull();
    expect(queryByTestId("tiktok-pixel")).toBeNull();
    expect(queryByTestId("snap-pixel")).toBeNull();
  });

  it("DOES get gtag, carrying the refusal", () => {
    // Deliberate, and the opposite of the three above. Google Consent Mode wants to be
    // told about a refusal rather than not exist — in the EEA and UK, Google Ads
    // requires it — and a refused visitor produces a cookieless ping Google may receive.
    const { getByTestId } = renderScripts();
    const consent = getByTestId("gtag-consent");
    expect(consent.textContent).toContain("'ad_storage':'denied'");
    expect(consent.textContent).toContain("'analytics_storage':'denied'");
  });
});

describe("a visitor who accepted", () => {
  beforeEach(() => {
    document.cookie = "country=GB; path=/";
    consentCookie(1, 1);
  });

  it("gets every configured pixel, initialised with its own id", () => {
    const { getByTestId } = renderScripts();
    expect(getByTestId("meta-pixel").textContent).toContain("fbq('init','META123')");
    expect(getByTestId("tiktok-pixel").textContent).toContain("ttq.load('TT123')");
    expect(getByTestId("snap-pixel").textContent).toContain("snaptr('init','SNAP123')");
  });

  it("tells Google the grant, and configures BOTH Google ids", () => {
    const { getByTestId } = renderScripts();
    expect(getByTestId("gtag-consent").textContent).toContain("'ad_user_data':'granted'");
    const config = getByTestId("gtag-config").textContent ?? "";
    expect(config).toContain("gtag('config','G-123')");
    expect(config).toContain("gtag('config','AW-123')");
  });

  it("declares the consent DEFAULT as denied before the update", () => {
    // Order is the contract: gtag.js drains `dataLayer` in sequence, and a default that
    // arrives after an event is a default that arrived too late.
    const text = renderScripts().getByTestId("gtag-consent").textContent ?? "";
    expect(text.indexOf("'default'")).toBeLessThan(text.indexOf("'update'"));
  });
});

describe("the switches", () => {
  beforeEach(() => {
    document.cookie = "country=NG; path=/";
    consentCookie(1, 1);
  });

  it("emits nothing at all when tracking is off store-wide", () => {
    const { container } = renderScripts({ ...ALL_CHANNELS, tracking_enabled: false });
    expect(container.querySelectorAll("script")).toHaveLength(0);
  });

  it("skips a channel that has no id, rather than loading a tag that cannot work", () => {
    const { queryByTestId } = renderScripts({
      ...ALL_CHANNELS,
      channels: [{ code: "meta", pixel_id: "", secondary_id: "" }],
    });
    expect(queryByTestId("meta-pixel")).toBeNull();
  });
});
