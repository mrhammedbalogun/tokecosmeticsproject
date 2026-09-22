/**
 * An order, read as the identifiers Google can match on (Plan-44, 2026-09-22).
 *
 * Shared by the confirmation page and the account order page so the two surfaces cannot
 * describe the same customer differently — the same argument `value.ts` makes about the
 * two halves of one purchase disagreeing about the amount.
 *
 * ── THE ADDRESS SNAPSHOT IS THE SOURCE ──────────────────────────────────────────────
 *
 * `order.shipping_address` is a point-in-time JSON copy, not a live `Address` row, and
 * it is deliberately the source here for the reason `marketing/events._user_signals`
 * gives on the server: the customer may have edited or deleted that address since, and
 * what was true at purchase is the stable thing. Reading it defensively (an untyped
 * blob) matches `AddressBlock`, which is the other consumer of the same shape.
 *
 * ── WHAT IS NOT HERE, AND MUST NOT BE ───────────────────────────────────────────────
 *
 * The emailed tracking link (`/orders/[number]?token=…`) renders from `OrderTracking`,
 * which carries NO email, phone or address — a forwardable URL is not a place to put
 * them. That page therefore cannot contribute enhanced-conversion data, and the fix for
 * that is not to widen `OrderTrackingSerializer`. See the note in `lib/orders.ts`.
 */
import type { GoogleUserData } from "@/lib/tracking/events";
import type { OrderDetail } from "@/lib/orders";

function field(address: Record<string, unknown> | null, key: string): string {
  const value = address?.[key];
  return typeof value === "string" ? value : "";
}

export function googleUserDataFromOrder(order: OrderDetail): GoogleUserData {
  const address = order.shipping_address;
  return {
    email: order.email,
    phone: order.phone,
    firstName: field(address, "first_name"),
    lastName: field(address, "last_name"),
    street: field(address, "line1"),
    // `city_text`/`state_text` are the rendered names the snapshot carries; the server
    // reads `area`/`city_text` and `state` off the same blob. Either spelling is a
    // locality string to Google, so both are tried rather than assuming one shape.
    city: field(address, "city_text") || field(address, "area"),
    region: field(address, "state_text") || field(address, "state"),
    postcode: field(address, "postcode"),
    // The order's own market, not the browsing cookie's — `country_code` when the
    // snapshot has it, else the order's market code.
    country: field(address, "country_code") || order.country,
  };
}
