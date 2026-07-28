/**
 * Invoice download proxy — GET /api/orders/{number}/invoice.
 *
 * INVARIANT: forward the CUSTOMER's token and never any privileged credential.
 * Authorization lives in exactly one place — the backend queryset (`OrderInvoiceView`,
 * filtered to `user=request.user` FOR NON-STAFF CALLERS, so a stranger's order 404s;
 * staff are handed the unfiltered queryset there on purpose, backend/apps/orders/
 * views.py:88). Nothing here decides who may read an invoice; a second opinion in the
 * BFF is a second place to get it wrong, and the one that drifts.
 *
 * Exists at all because the credential is unreachable from the browser: the access token
 * lives in an httpOnly cookie on the STOREFRONT origin, so a link straight to the API
 * origin carries no Authorization header and no cookie. The download must be issued
 * server-side, which is what makes this route a proxy rather than a redirect.
 */
import { fetchWithAuthRaw } from "@/lib/session";
import { LOGIN_PATH, withNext } from "@/lib/auth-guard";

/**
 * Strict allowlist on purpose. The current order-number format is TC-\d+ and no legacy
 * importer exists yet — Plan-22 widens this if real legacy numbers ever demand it.
 *
 * Defence in depth rather than the load-bearing control: the upstream path is escaped
 * independently below, so widening this class cannot by itself let `number` address
 * something other than one order's invoice. The one thing that IS still regex-dependent
 * is the Content-Disposition filename — see the note there before widening.
 */
const ORDER_NUMBER = /^[A-Za-z0-9-]{1,32}$/;

/** Bare 404, no body. Named apart from `next/navigation`'s `notFound()`, which throws. */
const blank404 = () => new Response(null, { status: 404 });

/** Where this route's only caller lives — both redirect targets are built from it. */
const orderPath = (number: string) => `/account/orders/${encodeURIComponent(number)}`;

const seeOther = (location: string) =>
  new Response(null, { status: 303, headers: { Location: location } });

export async function GET(_req: Request, ctx: { params: Promise<{ number: string }> }) {
  // Next hands `number` back DECODED, so this is the raw value, not the URL segment.
  const { number } = await ctx.params;
  // Reject before the network: a malformed number cannot name a real order, and the
  // upstream must never be asked a question built from unvalidated input.
  if (!ORDER_NUMBER.test(number)) return blank404();

  // One silent refresh + retry lives inside fetchWithAuthRaw; a 401 here is post-refresh.
  //
  // Encoded even though the allowlist above already guarantees nothing needs escaping:
  // path safety must not DEPEND on that regex, which Plan-22 is already slated to widen.
  // When it does, this line is still correct on its own.
  const upstream = await fetchWithAuthRaw(`/orders/${encodeURIComponent(number)}/invoice.pdf`);

  if (upstream.status === 200) {
    const headers = new Headers({
      "Content-Type": "application/pdf",
      // Overrides the upstream's `inline`: this is what makes the order page's plain
      // <a> download the file instead of navigating away to render it.
      //
      // STILL REGEX-DEPENDENT, unlike the path above: `number` is interpolated inside a
      // quoted filename, so admitting `"` or CRLF to ORDER_NUMBER would break out of
      // this header. Escape here first if Plan-22 widens that class.
      "Content-Disposition": `attachment; filename="${number}.pdf"`,
      // An invoice carries the customer's name, address and billing details. It must
      // never land in a shared cache.
      "Cache-Control": "private, no-store",
    });
    // Only header forwarded from upstream: everything else is decided here.
    const length = upstream.headers.get("content-length");
    if (length) headers.set("Content-Length", length);
    // Streamed, never buffered — the PDF passes through untouched.
    return new Response(upstream.body, { status: 200, headers });
  }

  // Nothing below returns any of the upstream's bytes. An unread body pins the
  // underlying connection, so release it on every one of these paths.
  await upstream.body?.cancel();

  if (upstream.status === 401) {
    // Session genuinely dead. A 303 suits a top-level navigation: the customer lands on
    // login rather than on a broken download. (The link carries no `download` attribute
    // for this reason — the ruling lives on the <a> in the order detail page.)
    //
    // The target hardcodes the ACCOUNT area, which assumes the account order detail page
    // is this route's only caller. It has to stay that way: the GUEST TRACKING page must
    // not link here. The upstream is owner-only with no tracking-token path, so a guest
    // would be bounced to a login they may have no account for, over an order the
    // tracking link otherwise lets them see.
    return seeOther(withNext(LOGIN_PATH, orderPath(number)));
  }

  // Collapsed deliberately: the backend 403s an anonymous caller and 404s a stranger's
  // order. Answering differently would confirm which order numbers exist. Bare, not a
  // redirect: reaching here means the URL was tampered with, not that anything broke.
  if (upstream.status === 403 || upstream.status === 404) return blank404();

  // Genuine upstream failure. A blank 502 body strands a NAVIGATING browser on a white
  // page with no way back, so hand the failure to the order page — the only caller —
  // as a flag it knows how to explain. The upstream's own body is still never forwarded;
  // it can carry stack traces.
  return seeOther(`${orderPath(number)}?invoice=unavailable`);
}
