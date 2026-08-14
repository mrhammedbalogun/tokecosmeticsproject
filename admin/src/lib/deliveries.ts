/**
 * Shapes and query handling for the deliveries table (Plan-35). No fetching — that is
 * `app/(shell)/deliveries/gig/page.tsx`.
 *
 * THE FILTER VOCABULARY IS THE ENDPOINT'S (`AdminGigShipmentListView.get_queryset`
 * reads `status`, `origin`, `service`, `placed_after`, `placed_before` and ignores
 * everything else), same contract as `lib/orders.ts`.
 */

/** `GigShipment.STATUSES` in `backend/apps/delivery/models.py`, in lifecycle order. */
export const SHIPMENT_STATUSES = [
  "quoted",
  "created",
  "in_transit",
  "delivered",
  "create_unconfirmed",
  "abandoned",
] as const;

export type ShipmentStatus = (typeof SHIPMENT_STATUSES)[number];

export function isShipmentStatus(value: string): value is ShipmentStatus {
  return (SHIPMENT_STATUSES as readonly string[]).includes(value);
}

/** One row of `GET /admin/gig-shipments/` — composed from snapshots server-side, so
 *  origin/destination render as they were at placement, not as the tables read today. */
export interface GigShipmentRow {
  order_number: string;
  placed_at: string | null;
  status: ShipmentStatus;
  waybill: string;
  /** id 0 = the built-in env origin (pre-Plan-34 shipments included). */
  origin: { id: number; name: string };
  service: "door" | "pickup";
  destination: string;
  customer_name: string;
  customer_phone: string;
  charged: string;
  cost: string | null;
  currency: string;
  last_scan: Record<string, unknown>;
  last_tracked_at: string | null;
}

export interface GigShipmentPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: GigShipmentRow[];
}

export interface GigShipmentFilters {
  status?: ShipmentStatus;
  /** A sender-location id as a string; "0" = the built-in origin. */
  origin?: string;
  service?: "door" | "pickup";
  placed_after?: string;
  placed_before?: string;
  page: number;
}

export function parseGigShipmentFilters(params: URLSearchParams): GigShipmentFilters {
  const filters: GigShipmentFilters = { page: parsePage(params.get("page")) };

  const status = params.get("status")?.trim();
  // Unrecognised values are DROPPED, not forwarded: the backend would filter to nothing
  // and an empty table reads as "no shipments" rather than as a typo in the URL.
  if (status && isShipmentStatus(status)) filters.status = status;

  const service = params.get("service")?.trim();
  if (service === "door" || service === "pickup") filters.service = service;

  const origin = params.get("origin")?.trim();
  if (origin && /^\d+$/.test(origin)) filters.origin = origin;

  for (const key of ["placed_after", "placed_before"] as const) {
    const value = params.get(key)?.trim();
    // Blank is ABSENT — a GET form submits every field it contains.
    if (value) filters[key] = value;
  }

  return filters;
}

function parsePage(raw: string | null): number {
  if (!raw || !/^\d+$/.test(raw)) return 1;
  const page = Number(raw);
  return page >= 1 ? page : 1;
}

export function gigShipmentsQueryString(filters: GigShipmentFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.origin !== undefined) params.set("origin", filters.origin);
  if (filters.service) params.set("service", filters.service);
  if (filters.placed_after) params.set("placed_after", filters.placed_after);
  if (filters.placed_before) params.set("placed_before", filters.placed_before);
  if (filters.page > 1) params.set("page", String(filters.page));
  return params.toString();
}

/** The newest tracking scan as one displayable string, or null when there is nothing
 *  to say. Webhook events carry human text in `ScanStatusComment`; the poll's entries
 *  carry a bare code in `Status` ("MAHD") — prefer the sentence, fall back to the code,
 *  and never parse beyond that: the scan shape is GIG's to change (tracking.py stores
 *  it verbatim for exactly this reason). */
export function lastScanStatus(row: {
  last_scan: Record<string, unknown>;
}): string | null {
  for (const key of ["ScanStatusComment", "Status"]) {
    const value = row.last_scan?.[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return null;
}
