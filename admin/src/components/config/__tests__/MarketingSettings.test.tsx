/**
 * The Marketing card's addressing rule and summary line (2026-09-19).
 *
 * The admin, the outbox gate and the test endpoint all used to ask every channel for a
 * pixel id first. For Google that was wrong — its server half is addressed by a customer
 * id and a conversion action id and never reads the `AW-` id — and production showed it:
 * 224 purchases skipped as `no_pixel_id`, the test button refusing a live-validated
 * channel, and this card saying "no ID — nothing is loading" about all of it.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarketingSettings, summary } from "@/components/config/MarketingSettings";
import { serverAddressed, type MarketingChannelRow } from "@/lib/marketing-config";

function row(overrides: Partial<MarketingChannelRow> = {}): MarketingChannelRow {
  return {
    code: "google_ads",
    label: "Google Ads",
    is_enabled: true,
    pixel_id: "",
    secondary_id: "",
    server_account_id: "3352855298",
    server_destination_id: "7577766208",
    browser_enabled: false,
    server_enabled: true,
    test_event_code: "",
    credential_configured: true,
    missing_settings: [],
    has_server_side: true,
    ...overrides,
  };
}

describe("serverAddressed — mirrors MarketingChannel.server_address_problem", () => {
  // The same four cases `test_the_address_rule_lives_in_one_place` pins on the backend.
  it("addresses Google by its two server ids, with or without a pixel id", () => {
    expect(serverAddressed(row({ pixel_id: "" }))).toBe(true);
    expect(serverAddressed(row({ server_account_id: "", server_destination_id: "" }))).toBe(false);
  });

  it("still requires the pixel id for the channels whose pixel IS the address", () => {
    expect(serverAddressed(row({ code: "meta", pixel_id: "" }))).toBe(false);
    expect(serverAddressed(row({ code: "meta", pixel_id: "123" }))).toBe(true);
  });
});

describe("summary", () => {
  it("reports production's Google config as a working server half", () => {
    // pixel '' + browser off + server ids set: exactly what was live on 2026-09-19.
    expect(summary(row(), true)).toBe("server");
  });

  it("names the missing Google destination rather than a missing pixel", () => {
    expect(summary(row({ server_account_id: "" }), true)).toBe("server (no destination)");
  });

  it("warns that a Google tag with no label loads but counts no purchase", () => {
    expect(summary(row({ browser_enabled: true, pixel_id: "AW-1" }), true))
      .toBe("pixel (no conversion label) + server");
    expect(summary(row({ browser_enabled: true, pixel_id: "AW-1", secondary_id: "Lbl" }), true))
      .toBe("pixel + server");
  });

  it("reports each half's own gap for a pixel-addressed channel", () => {
    expect(summary(row({ code: "meta", browser_enabled: true, pixel_id: "" }), true))
      .toBe("pixel (no ID) + server (no ID)");
  });

  it("still says off before it says anything else", () => {
    expect(summary(row(), false)).toBe("off — tracking is switched off store-wide");
    expect(summary(row({ is_enabled: false }), true)).toBe("off");
  });
});

describe("the test button", () => {
  const settings = {
    tracking_enabled: true, purchase_value_basis: "goods" as const,
    consent_required_countries: ["GB"], consent_version: 1,
  };

  it("is offered for a Google channel with no pixel id", () => {
    render(<MarketingSettings settings={settings} channels={[row()]} />);
    expect(screen.getByRole("button", { name: "Send test event" })).toBeEnabled();
  });

  it("is withheld while Google has nowhere to send", () => {
    render(<MarketingSettings settings={settings} channels={[row({ server_destination_id: "" })]} />);
    expect(screen.getByRole("button", { name: "Send test event" })).toBeDisabled();
  });
});
