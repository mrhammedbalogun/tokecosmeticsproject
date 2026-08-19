/** Typed order fetchers + types. Server-side only — mirrors lib/checkout.ts. Shared by
 * the confirmation page and the account order pages; each page owns its own fetch, so
 * nothing here caches or memoises across callers.
 *
 * Not every fetcher here is session-based: the backend's order detail endpoint is
 * AllowAny and also serves a signed `?token=` tracking link, so a public token fetcher
 * (plain apiFetch, no session) belongs in this module alongside the authed ones. */
import { notFound } from "next/navigation";
import { ApiError, apiFetch } from "@/lib/api";
import { fetchWithAuthOrBounce } from "@/lib/session";

export interface OrderItem {
  /** A pre-joined STRING ("Size: 150ml"), not the cart's {option: value} map — an order
   * line is a point-in-time snapshot and OrderItem.variant_name is a CharField on the
   * backend. Typing it as a Record made the confirmation page call Object.values() on a
   * string and render it one character at a time ("S / i / z / e / ..."). */
  product_name: string; variant_name: string; sku: string;
  quantity: number; unit_price: string; line_total: string;
  unit_price_display: string; line_total_display: string; image_url: string | null;
}
export interface OrderDetail {
  number: string; status: string; placed_at: string; currency: string;
  /** The order's market code ("NG") — the pay-again UI lists gateways for the
   * ORDER's market, not the browsing cookie's. Full serializer only. */
  country: string;
  /** The contact the order was placed with (the account's at placement, or the
   * guest-typed one). On the FULL serializer only — absent from OrderTracking. */
  email: string; phone: string;
  subtotal: string; discount_total: string; shipping_total: string; tax_total: string;
  /** The market's name for the tax line ("VAT", "Sales Tax"); serializer default keeps
   * it present on every order. */
  tax_label: string;
  grand_total: string; grand_total_display: string; delivery_option_name: string | null;
  shipping_address: Record<string, unknown> | null; billing_address: Record<string, unknown> | null;
  customer_note: string; payment_gateway: string; items: OrderItem[];
  /** Always present on the owner serializer, but EMPTY STRINGS until fulfilment fills
   * them in — "set" means non-empty, not "not undefined". Either one can be set without
   * the other (a carrier chosen before the consignment number exists). */
  tracking_carrier: string; tracking_number: string;
  /** The latest GIG scan verbatim, or null for non-GIG orders and pre-waybill shipments
   * (backend `OrderSerializer.get_gig_tracking`). Owner view only — deliberately absent
   * from the redacted OrderTracking below. */
  gig_tracking?: {
    status: string;
    last_scan: Record<string, unknown>;
    last_tracked_at: string | null;
  } | null;
  /** Centre-pickup snapshot from placement (32b slice 4), or null for door
   * delivery. Known before any waybill exists — render "collect from" on it. */
  pickup_centre?: { id: number; station_id?: number; name: string; address: string } | null;
}

/**
 * The redacted, bearer-token view (backend `OrderTrackingSerializer`) — NOT a subset of
 * OrderDetail by accident: no address, no email, no phone, no payment gateway, no
 * customer note and no money BREAKDOWN, only the grand total. The signed token travels in
 * an order email, which is forwardable, so every field listed here is one the backend is
 * content to have read by whoever ends up holding the link. Widening this type means
 * widening `OrderTrackingSerializer` first, and that is a privacy decision, not a typing
 * one.
 */
export interface OrderTracking {
  number: string; status: string; placed_at: string; currency: string;
  grand_total: string; grand_total_display: string; delivery_option_name: string | null;
  /** Same semantics as OrderDetail's pair: EMPTY STRINGS until fulfilment fills them in,
   * and either can be set without the other. */
  tracking_carrier: string; tracking_number: string; items: OrderItem[];
}

/** The list endpoint's row (backend `OrderListSerializer`) — a strict subset of
 * OrderDetail plus `item_count`, which counts UNITS (sum of quantities), not lines. */
export interface OrderListItem {
  number: string; status: string; placed_at: string; currency: string;
  grand_total: string; grand_total_display: string; item_count: number;
  items: OrderItem[];
}

/** DRF's PageNumberPagination envelope. Structurally identical to catalog.ts's copy and
 * deliberately not shared: the two modules describe different APIs that happen to use the
 * same pagination class today, and a cross-import would couple order fetchers to the
 * catalog module for a three-field type. */
export interface Paginated<T> {
  count: number; next: string | null; previous: string | null; results: T[];
}

/** One date format across every order surface (list, detail, invoice) — "24 Jul 2026".
 * Built once at module scope; constructing an Intl formatter per row is measurably slow.
 *
 * Formats in the SERVER's timezone, which vitest.config.mts pins to UTC so assertions are
 * hermetic. SERVER COMPONENTS ONLY, like everything in this module: it is pure, but the
 * module's import of lib/session pulls in next/headers, so a Client Component importing
 * this helper would fail the build. Copy it to a client-safe module if that day comes. */
const ORDER_DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", year: "numeric",
});
export function formatOrderDate(iso: string): string {
  return ORDER_DATE.format(new Date(iso));
}

/**
 * Authed order detail. Two callers — the checkout confirmation page and the account
 * order-detail page — both SERVER COMPONENTS, hence `fetchWithAuthOrBounce` rather than
 * `fetchWithAuth`: a Server Component cannot persist a rotated token, so refreshing here
 * would blacklist the customer's refresh token and end their session behind a page that
 * still rendered correctly.
 *
 * `currentPath` is where the bounce sends the user back to, so each caller passes its OWN
 * page path (URL-encoded as the browser has it), not this endpoint's.
 *
 * There is no anonymous path to guard *here*: `orders/views.py` 403s a caller with no
 * auth and no signed tracking token, and neither the confirmation page nor the account
 * order-detail page ever carries a token.
 *
 * The endpoint itself is AllowAny and does serve a signed `?token=` tracking link — a
 * public/token caller must use the dedicated tracking fetcher (plain apiFetch, no
 * session), never this function, which would bounce a guest to login instead.
 */
export async function getOrder(number: string, country: string, currentPath: string) {
  // Encoded: migrated legacy numbers are not guaranteed URL-safe, and an unencoded "#"
  // truncates the upstream path at the fragment while "/" invents a URL segment — either
  // way Django routes the request somewhere else and the customer sees a 404 for an
  // order that exists. Both callers already encode it into their own page paths.
  return fetchWithAuthOrBounce<OrderDetail>(`/orders/${encodeURIComponent(number)}/`, currentPath, {
    country, cache: "no-store",
  });
}

/**
 * `getOrder` with the not-found mapping every page-level caller needs. Both order pages
 * had an identical private copy of this; the error discipline below is subtle enough that
 * two copies is one too many.
 *
 * 403 as well as 404: the backend deliberately refuses to distinguish "no such order"
 * from "not yours" (orders/views.py filters by owner so a stranger's order 404s — a 403
 * would confirm it exists). Mirror that here rather than surfacing an error page.
 *
 * Everything else rethrown UNTOUCHED — including the NEXT_REDIRECT that `getOrder` throws
 * to renew a stale session. A catch-all here would swallow the bounce and log the
 * customer out for good.
 */
export async function getOrderOrNotFound(
  number: string, country: string, currentPath: string,
): Promise<OrderDetail> {
  try {
    return await getOrder(number, country, currentPath);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 403)) notFound();
    throw e;
  }
}

/**
 * The guest tracking view of an order, unlocked by the signed `?token=` the backend puts
 * in order emails (`backend/apps/orders/emails.py`). Returns the REDACTED payload.
 *
 * PLAIN `apiFetch` — never `fetchWithAuth*`, per the module header and the rule restated
 * on `getOrder`. The caller is a public page: an auth fetcher would bounce a guest to
 * login (and, on a stale cookie, drag the tracking link into the refresh flow) for a page
 * that needs no session at all. Nothing here reads cookies.
 *
 * No `country`: the order carries its own `currency` and pre-rendered
 * `grand_total_display`, so X-Country has no effect on this response.
 *
 * `no-store` for the same reason as the authed fetchers — status and tracking numbers
 * change out from under any cache — plus the response is keyed by a bearer token that
 * must never be shared between visitors.
 *
 * Bad/expired/mismatched token → ApiError 404 `{"error":"invalid_token"}`, deliberately
 * indistinguishable from a number that never existed. The caller maps it; do NOT map it
 * to notFound() here (the page renders a friendly stale-link state instead).
 */
/**
 * The FULL order view for a guest-checkout order (Plan-38), unlocked by the
 * guest-order token the checkout BFF holds in the httpOnly `guest_order` cookie.
 * PLAIN `apiFetch` for the same reason as `getTrackedOrder`: the caller (the
 * confirmation page serving a guest) has no session, and an auth fetcher would
 * bounce the guest to login over a page their cookie already opens. The backend
 * reads the number OUT of the token, so a tampered URL 404s.
 */
export async function getGuestOrder(number: string, guestToken: string) {
  return apiFetch<OrderDetail>(
    `/orders/${encodeURIComponent(number)}/?guest_token=${encodeURIComponent(guestToken)}`,
    { cache: "no-store" },
  );
}

export async function getTrackedOrder(number: string, token: string) {
  // Both halves encoded. The number for the same reason as `getOrder`. The token needs
  // nothing escaped TODAY — `django.core.signing` emits URL-safe base64 with ":"
  // separators (backend/apps/orders/tokens.py) — so this is forward-proofing against a
  // future token format, not a live fix. Cheap insurance; do not "simplify" it away.
  return apiFetch<OrderTracking>(
    `/orders/${encodeURIComponent(number)}/?token=${encodeURIComponent(token)}`,
    { cache: "no-store" },
  );
}

/**
 * The signed-in shopper's own orders, newest first (the backend owner-filters and orders
 * by `-placed_at`; IsAuthenticated, so this call IS the page's auth gate — no extra
 * requireAuth on top of it).
 *
 * `no-store` because order status changes out from under any cache, and the response is
 * per-user: a shared cache entry here would serve one customer's orders to another.
 *
 * DRF 404s a page beyond the last one, so the caller must map ApiError 404 → notFound().
 */
export async function getOrders(page: number, currentPath: string) {
  return fetchWithAuthOrBounce<Paginated<OrderListItem>>(`/orders/?page=${page}`, currentPath, {
    cache: "no-store",
  });
}
