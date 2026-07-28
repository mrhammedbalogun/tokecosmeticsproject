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
import { fetchWithAuthRaw, RscCookieWriteError } from "@/lib/session";
import { ApiError, drainBody } from "@/lib/api";
import { LOGIN_PATH, withNext } from "@/lib/auth-guard";

/**
 * Strict allowlist on purpose. The current order-number format is TC-\d+ and no legacy
 * importer exists yet — Plan-22 widens this if real legacy numbers ever demand it.
 *
 * Defence in depth rather than the load-bearing control: both places `number` is
 * interpolated — the upstream path and the Content-Disposition filename — escape it
 * themselves, so widening this class cannot by itself produce a bad URL or a broken
 * header.
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
  //
  // The try wraps ONLY this call. Two very different throws arrive here:
  //  - ApiError 401, when the internal refresh is REJECTED (expired or blacklisted
  //    refresh token). Routine session expiry, not a fault — the same dead session the
  //    401 branch below handles, just surfacing as a throw because it happened during
  //    the refresh rather than on the invoice request.
  //  - anything else: the network failing (backend down, DNS, timeout), the likeliest
  //    way this route breaks in production. Unhandled it renders a blank 500 to a
  //    NAVIGATING browser, the exact UX the non-200 branch below exists to avoid.
  let upstream: Response;
  try {
    upstream = await fetchWithAuthRaw(`/orders/${encodeURIComponent(number)}/invoice.pdf`);
  } catch (e) {
    // The one error that must NOT be softened. It is raised inside the fetcher (before
    // the network) when a Server Component calls it, and swallowing it is how a dead
    // session gets papered over — see lib/session.ts. Scoping the try tightly does not
    // help, because the throw happens inside the callee; only rethrowing does.
    if (e instanceof RscCookieWriteError) throw e;
    // Dead refresh token — send them to login, and do NOT log. This fires on every
    // 14-day expiry, and a wolf-crying error line trains everyone to ignore the only
    // console.error in the codebase.
    //
    // Both statuses, matching api/auth/refresh-redirect: SimpleJWT answers 401 for a
    // rejected token and 400 for one that is invalid or ALREADY SPENT — the loser of a
    // concurrent rotation (ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION). Same dead
    // session, same remedy; only the reason differs.
    if (e instanceof ApiError && (e.status === 401 || e.status === 400)) {
      return seeOther(withNext(LOGIN_PATH, orderPath(number)));
    }
    // Nothing else reports this: the storefront has no Sentry, and catching here removes
    // the error Next would otherwise have logged. Without this line a backend outage is
    // completely silent.
    console.error("[invoice] upstream fetch failed", e);
    return seeOther(`${orderPath(number)}?invoice=unavailable`);
  }

  if (upstream.status === 200) {
    const headers = new Headers({
      "Content-Type": "application/pdf",
      // Overrides the upstream's `inline`: this is what makes the order page's plain
      // <a> download the file instead of navigating away to render it.
      //
      // Escaped for the same reason as the path, and byte-identical for every name the
      // allowlist admits today (alphanumerics and `-` pass through untouched). It means
      // a `"` or a CRLF could not break out of this quoted filename even if ORDER_NUMBER
      // were widened to admit them — the header is safe independent of the regex.
      "Content-Disposition": `attachment; filename="${encodeURIComponent(number)}.pdf"`,
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
  // underlying connection, so release it on every one of these paths — by reading,
  // not cancelling; see drainBody for why cancel() stalls under Next's fetch tee.
  await drainBody(upstream);

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
