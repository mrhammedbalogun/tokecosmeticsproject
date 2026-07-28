/**
 * Invoice download proxy — GET /api/orders/{number}/invoice.
 *
 * INVARIANT: forward the CUSTOMER's token and never any privileged credential.
 * Authorization lives in exactly one place — the backend queryset
 * (`OrderInvoiceView`, filtered to `user=request.user`, so a stranger's order 404s).
 * Nothing here decides who may read an invoice; a second opinion in the BFF is a second
 * place to get it wrong, and the one that drifts.
 *
 * Exists at all because the credential is unreachable from the browser: the access token
 * lives in an httpOnly cookie on the STOREFRONT origin, so a link straight to the API
 * origin carries no Authorization header and no cookie. The download must be issued
 * server-side, which is what makes this route a proxy rather than a redirect.
 */
import { fetchWithAuthRaw } from "@/lib/session";
import { LOGIN_PATH } from "@/lib/auth-guard";

/**
 * Strict allowlist on purpose. The current order-number format is TC-\d+ and no legacy
 * importer exists yet — Plan-22 widens this if real legacy numbers ever demand it.
 *
 * It also makes path-injection into the upstream URL impossible: no `/`, `.` or `%`
 * survives, so `number` can address nothing but one order's invoice.
 */
const ORDER_NUMBER = /^[A-Za-z0-9-]{1,32}$/;

/** Bare 404, no body. Named apart from `next/navigation`'s `notFound()`, which throws. */
const blank404 = () => new Response(null, { status: 404 });

export async function GET(_req: Request, ctx: { params: Promise<{ number: string }> }) {
  // Next hands `number` back DECODED, so this is the raw value, not the URL segment.
  const { number } = await ctx.params;
  // Reject before the network: a malformed number cannot name a real order, and the
  // upstream must never be asked a question built from unvalidated input.
  if (!ORDER_NUMBER.test(number)) return blank404();

  // One silent refresh + retry lives inside fetchWithAuthRaw; a 401 here is post-refresh.
  const upstream = await fetchWithAuthRaw(`/orders/${number}/invoice.pdf`);

  if (upstream.status === 200) {
    const headers = new Headers({
      "Content-Type": "application/pdf",
      // Overrides the upstream's `inline` — this route is only ever reached from a
      // download link.
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
    // The session is genuinely dead. This URL is reached by a top-level navigation, so a
    // redirect lands the user on login instead of on a broken download.
    //
    // CAVEAT for whoever meets this in the wild: the caller is an `<a download>`, and a
    // browser keeps applying `download` across the redirect — so the login page may be
    // SAVED rather than shown. Still better than handing the customer a 0-byte PDF, and
    // the window is tiny (the page behind the link is itself auth-gated). If it turns
    // out to bite, the fix belongs on the page — swap the plain <a> for a fetch that can
    // read the status — not here.
    return new Response(null, {
      status: 303,
      headers: {
        Location: `${LOGIN_PATH}?next=/account/orders/${encodeURIComponent(number)}`,
      },
    });
  }

  // Collapsed deliberately: the backend 403s an anonymous caller and 404s a stranger's
  // order. Answering differently would confirm which order numbers exist.
  if (upstream.status === 403 || upstream.status === 404) return blank404();

  // Upstream error bodies are not ours to leak — they can carry stack traces.
  return new Response(null, { status: 502 });
}
