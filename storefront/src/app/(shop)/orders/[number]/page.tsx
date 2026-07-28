/** Guest order tracking — the login-free deep link order emails carry
 * (`${FRONTEND_URL}/orders/{number}?token=…`, backend/apps/orders/emails.py). The slug is
 * pinned by those emails; it is not ours to rename.
 *
 * PUBLIC page. It reads no cookies, calls no auth fetcher and never redirects: the whole
 * point is that a customer with the email — signed in or not, on any device — sees their
 * order. The `?token=` is the only credential involved, and `proxy.ts` gates `/account*`
 * only, so this route needs nothing there.
 *
 * Lives under `(shop)` so the link out of an email lands on the real site with header,
 * footer and a way to keep shopping, rather than a bare panel. */
import type { Metadata } from "next";
import Link from "next/link";
import { ApiError } from "@/lib/api";
import { first } from "@/lib/search-params";
import { formatOrderDate, getTrackedOrder, type OrderTracking } from "@/lib/orders";
import { OrderItems } from "@/components/orders/OrderItems";
import { StatusChip } from "@/components/orders/StatusChip";
import { TrackingBlock } from "@/components/orders/TrackingBlock";

type Params = Promise<{ number: string }>;
type Search = Promise<{ [key: string]: string | string[] | undefined }>;

/** noindex AND nofollow: a URL that reaches this page carries a live bearer token, so it
 * must not enter an index or be walked onward from.
 *
 * Static metadata with NO order number in the title, deliberately. `params` is available
 * and the account pages do title theirs, but this link is opened from a mail app on
 * whatever device is to hand — the title is what lands in browser history and syncs
 * across a shared or borrowed machine. A generic title costs nothing here (the page's own
 * heading names the order to the person actually looking at it). */
export const metadata: Metadata = {
  title: "Track order",
  robots: { index: false, follow: false },
  // This URL's query string IS a credential, and a referrer header would hand it to every
  // host the page links out to. Modern browsers default to strict-origin-when-cross-origin
  // (which already strips the query), but that is their choice, not ours — state it.
  referrer: "no-referrer",
};

/**
 * `null` means "render the invalid-link state". ONLY a 404 maps to it — the backend
 * answers a garbage, expired or mismatched token with 404 `{"error":"invalid_token"}`.
 *
 * Everything else is rethrown UNTOUCHED: a 500 or a dead upstream must surface as an
 * error, not masquerade as an expired link. Swallowing it would tell a customer holding a
 * perfectly good link that it had expired, and send them off to sign in over what is
 * really our outage.
 */
async function loadTrackedOrder(number: string, token: string): Promise<OrderTracking | null> {
  try {
    return await getTrackedOrder(number, token);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

/**
 * Reveals NOTHING about whether the order exists. The backend's `invalid_token` 404 is
 * deliberately indistinguishable from a number that was never real, and this page keeps
 * it that way: identical words for a forged token, an expired one, and a stranger
 * guessing order numbers.
 *
 * Not `notFound()`: an order email outlives its token, so the typical visitor here is a
 * real customer with a stale link, and the site-wide 404 page has nothing useful to say
 * to them. The two pointers are the only real next steps — `/account/orders/{number}`
 * gates itself (a signed-out visitor gets the login bounce, a signed-in non-owner a 404),
 * so linking it leaks nothing either.
 */
function InvalidLink({ number }: { number: string }) {
  return (
    <section className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="font-display text-2xl">This tracking link is invalid or has expired</h1>
      <p className="mt-3 text-sm text-muted">
        Tracking links in order emails stop working after a while, and they only open the
        order they were sent for.
      </p>
      <div className="mt-6 flex flex-wrap items-center gap-4">
        {/* Encoded: `params` arrives DECODED, and migrated legacy numbers are not
            guaranteed URL-safe (an unencoded "/" would invent a route segment). */}
        <Link
          href={`/account/orders/${encodeURIComponent(number)}`}
          className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm font-medium text-surface transition-colors hover:bg-accent-strong"
        >
          Sign in to view your order
        </Link>
        <Link href="/products" className="text-sm text-accent-strong underline underline-offset-2">
          Continue shopping
        </Link>
      </div>
    </section>
  );
}

export default async function OrderTrackingPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: Search;
}) {
  const { number } = await params;
  // Trimmed, so `?token=` and `?token=%20` short-circuit like a missing one rather than
  // spending a round trip to be told what we already know.
  const token = first((await searchParams).token)?.trim();
  // No token → the invalid-link state directly, with NO upstream call: the backend 403s
  // an anonymous caller that carries none, so there is nothing to ask it.
  const order = token ? await loadTrackedOrder(number, token) : null;

  if (!order) return <InvalidLink number={number} />;

  return (
    <section className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="font-display text-2xl">Order {order.number}</h1>
      <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
        <span>Placed {formatOrderDate(order.placed_at)}</span>
        <StatusChip status={order.status} />
      </p>

      {/* Only when set: the redacted payload has no address to pair it with, so an empty
          "Delivery method — —" row would be a heading about nothing. */}
      {order.delivery_option_name && (
        <div className="mt-6">
          <h2 className="font-display text-lg">Delivery method</h2>
          <p className="mt-2 text-sm text-muted">{order.delivery_option_name}</p>
        </div>
      )}

      <TrackingBlock order={order} />

      <OrderItems items={order.items} />

      {/* One total line, NOT OrderTotals: the redacted serializer carries no subtotal,
          discount, shipping or tax — by design — so OrderTotals would render a column of
          blanks. No AddressBlock and no invoice link here either: the address is not in
          the payload, and the invoice route is owner-only (IsAuthenticated, no token
          path), so a guest clicking it would be bounced to a login for an order that may
          not even be theirs. */}
      <dl className="mt-6 border-t border-line pt-4 text-sm">
        <div className="flex justify-between gap-4 text-base font-medium">
          <dt>Total</dt>
          <dd>{order.grand_total_display}</dd>
        </div>
      </dl>

      <p className="mt-8 text-sm text-muted">
        <Link
          href={`/account/orders/${encodeURIComponent(order.number)}`}
          className="text-accent-strong underline underline-offset-2"
        >
          Sign in to your account
        </Link>{" "}
        for full order details.
      </p>
    </section>
  );
}
