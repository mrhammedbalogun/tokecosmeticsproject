import { describe, it, expect } from "vitest";
import {
  gigShipmentsQueryString,
  lastScanStatus,
  parseGigShipmentFilters,
} from "@/lib/deliveries";

const params = (qs: string) => new URLSearchParams(qs);

describe("parseGigShipmentFilters", () => {
  it("reads the endpoint's whole vocabulary", () => {
    const filters = parseGigShipmentFilters(
      params(
        "status=in_transit&origin=7&service=pickup" +
          "&placed_after=2026-01-01&placed_before=2026-12-31&page=3",
      ),
    );
    expect(filters).toEqual({
      status: "in_transit",
      origin: "7",
      service: "pickup",
      placed_after: "2026-01-01",
      placed_before: "2026-12-31",
      page: 3,
    });
  });

  it("treats a blank field as absent — a GET form submits every field it contains", () => {
    expect(parseGigShipmentFilters(params("status=&origin=&service="))).toEqual({ page: 1 });
  });

  it("keeps origin 0 — the built-in origin is a real filter choice, not falsy noise", () => {
    // Pre-Plan-34 shipments carry an empty snapshot; the endpoint maps 0 to them.
    const filters = parseGigShipmentFilters(params("origin=0"));
    expect(filters.origin).toBe("0");
    expect(gigShipmentsQueryString(filters)).toBe("origin=0");
  });

  it("drops unrecognised values rather than forwarding them", () => {
    // Forwarded, the backend filters to nothing and an empty table reads as
    // "no shipments" rather than as a typo in the URL.
    expect(parseGigShipmentFilters(params("status=nonsense")).status).toBeUndefined();
    expect(parseGigShipmentFilters(params("service=drone")).service).toBeUndefined();
    expect(parseGigShipmentFilters(params("origin=garbage")).origin).toBeUndefined();
  });

  it("defaults the page for anything that is not a positive integer", () => {
    expect(parseGigShipmentFilters(params("page=0")).page).toBe(1);
    expect(parseGigShipmentFilters(params("page=-2")).page).toBe(1);
    expect(parseGigShipmentFilters(params("page=abc")).page).toBe(1);
  });
});

describe("gigShipmentsQueryString", () => {
  it("round-trips what the parser accepted, omitting page 1", () => {
    const filters = parseGigShipmentFilters(
      params("status=quoted&origin=7&service=door&placed_after=2026-01-01"),
    );
    expect(gigShipmentsQueryString(filters)).toBe(
      "status=quoted&origin=7&service=door&placed_after=2026-01-01",
    );
    expect(gigShipmentsQueryString({ page: 1 })).toBe("");
    expect(gigShipmentsQueryString({ page: 2 })).toBe("page=2");
  });
});

describe("lastScanStatus", () => {
  it("prefers the webhook's human sentence over the poll's bare code", () => {
    expect(
      lastScanStatus({
        last_scan: { ScanStatusComment: "Shipment created", Status: "MCRT" },
      }),
    ).toBe("Shipment created");
    expect(lastScanStatus({ last_scan: { Status: "MAHD" } })).toBe("MAHD");
  });

  it("returns null when there is nothing to say", () => {
    expect(lastScanStatus({ last_scan: {} })).toBeNull();
    expect(lastScanStatus({ last_scan: { Status: "  " } })).toBeNull();
  });
});
