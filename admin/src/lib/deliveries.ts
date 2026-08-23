/**
 * Shapes and query handling for the deliveries tables (Plan-35: GIG; partner
 * shipments beside it). No fetching — that is `app/(shell)/deliveries/gig/page.tsx`
 * and `app/(shell)/deliveries/brandnpack/page.tsx`.
 *
 * THE FILTER VOCABULARY IS THE ENDPOINT'S (`AdminGigShipmentListView.get_queryset`
 * reads `status`, `origin`, `service`, `placed_after`, `placed_before`;
 * `AdminPartnerShipmentListView` reads `partner`, `status`, `delivered`,
 * `placed_after`, `placed_before` — both ignore everything else), same contract as
 * `lib/orders.ts`.
 */
import { isOrderStatus, type OrderStatus } from "@/lib/orders";

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

/** One row of `GET /admin/partner-shipments/` — the zone and address render from
 *  placement-time snapshots; `status` is the ORDER's status (a partner shipment has
 *  no lifecycle of its own), and `delivered_at` is the machine stamp that survives
 *  a refund-after-delivery. */
export interface PartnerShipmentRow {
  order_number: string;
  placed_at: string | null;
  status: OrderStatus;
  partner: { code: string; name: string };
  lcda: string;
  /** Blank when the snapshot never carried it (race fallback, label-only backfill). */
  dispatch_zone: string;
  destination: string;
  customer_name: string;
  customer_phone: string;
  charged: string;
  cost: string | null;
  currency: string;
  delivered_at: string | null;
}

export interface PartnerShipmentPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: PartnerShipmentRow[];
}

/** `partner` is NOT here — the page pins it ("/deliveries/brandnpack" is one
 *  partner's table) and appends it to the backend call, never to its own URL. */
export interface PartnerShipmentFilters {
  status?: OrderStatus;
  delivered?: "yes" | "no";
  placed_after?: string;
  placed_before?: string;
  page: number;
}

export function parsePartnerShipmentFilters(
  params: URLSearchParams,
): PartnerShipmentFilters {
  const filters: PartnerShipmentFilters = { page: parsePage(params.get("page")) };

  const status = params.get("status")?.trim();
  if (status && isOrderStatus(status)) filters.status = status;

  const delivered = params.get("delivered")?.trim();
  if (delivered === "yes" || delivered === "no") filters.delivered = delivered;

  for (const key of ["placed_after", "placed_before"] as const) {
    const value = params.get(key)?.trim();
    if (value) filters[key] = value;
  }

  return filters;
}

export function partnerShipmentsQueryString(filters: PartnerShipmentFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.delivered) params.set("delivered", filters.delivered);
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

// --- AAJ Express (Plan-43) --------------------------------------------------------------

/** `AajShipment.STATUSES` in `backend/apps/delivery/models.py`, in lifecycle order. */
export const AAJ_SHIPMENT_STATUSES = [
  "quoted",
  "booked",
  "created",
  "in_transit",
  "delivered",
  "returned",
  "voided",
  "create_unconfirmed",
  "abandoned",
] as const;

export type AajShipmentStatus = (typeof AAJ_SHIPMENT_STATUSES)[number];

export function isAajShipmentStatus(value: string): value is AajShipmentStatus {
  return (AAJ_SHIPMENT_STATUSES as readonly string[]).includes(value);
}

/** One row of `GET /admin/aaj-shipments/`. `quote_total` is AAJ's retail figure the
 *  customer was priced from; `cost` is what our account was charged at booking — the
 *  gap is margin the table shows rather than hides. */
export interface AajShipmentRow {
  order_number: string;
  placed_at: string | null;
  status: AajShipmentStatus;
  booking_id: string;
  tracking_id: string;
  origin: { id: number; name: string; state: string };
  destination: string;
  customer_name: string;
  customer_phone: string;
  quote_total: string | null;
  charged: string;
  cost: string | null;
  currency: string;
  last_scan: Record<string, unknown>;
  last_status: number | null;
  last_tracked_at: string | null;
}

export interface AajShipmentPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: AajShipmentRow[];
}

export interface AajShipmentFilters {
  status?: AajShipmentStatus;
  origin?: string;
  placed_after?: string;
  placed_before?: string;
  page: number;
}

export function parseAajShipmentFilters(params: URLSearchParams): AajShipmentFilters {
  const filters: AajShipmentFilters = { page: parsePage(params.get("page")) };
  const status = params.get("status")?.trim();
  if (status && isAajShipmentStatus(status)) filters.status = status;
  const origin = params.get("origin")?.trim();
  if (origin && /^\d+$/.test(origin)) filters.origin = origin;
  for (const key of ["placed_after", "placed_before"] as const) {
    const value = params.get(key)?.trim();
    if (value) filters[key] = value;
  }
  return filters;
}

export function aajShipmentsQueryString(filters: AajShipmentFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.origin !== undefined) params.set("origin", filters.origin);
  if (filters.placed_after) params.set("placed_after", filters.placed_after);
  if (filters.placed_before) params.set("placed_before", filters.placed_before);
  if (filters.page > 1) params.set("page", String(filters.page));
  return params.toString();
}

/** AAJ's newest event as one line: its description (the human sentence), else the
 *  scan type. Stored verbatim by tracking.py, so nothing deeper is parsed. */
export function aajLastScan(row: { last_scan: Record<string, unknown> }): string | null {
  for (const key of ["description", "scanType"]) {
    const value = row.last_scan?.[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return null;
}
