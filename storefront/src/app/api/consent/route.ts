import { cookies } from "next/headers";
import { CONSENT_COOKIE, CONSENT_MAX_AGE } from "@/lib/consent";

/**
 * Persist the visitor's cookie choice from the SERVER (2026-09-20).
 *
 * ── WHY THIS ROUTE EXISTS: SAFARI CAPS JAVASCRIPT COOKIES AT SEVEN DAYS ─────────────
 *
 * `ConsentProvider` used to write `tc_consent` with `document.cookie` and nothing else.
 * Safari's Intelligent Tracking Prevention caps every first-party cookie written that
 * way to 7 days — so a customer who pressed "Accept all" was asked again a week later,
 * and again the week after that, for ever.
 *
 * That is not a small edge. Measured on this shop's own buyers, 2026-09-20: of 384
 * orders carrying a user agent, 228 (59%) were iOS. Six in ten customers were being
 * re-asked roughly weekly no matter what they had clicked — which is exactly the
 * "accepting the cookies is stressful" complaint that reached Hammed.
 *
 * A cookie set by the SERVER in a `Set-Cookie` header is not subject to that cap. The
 * apex resolves to A records rather than a CNAME onto another registrable domain
 * (checked: 216.150.1.1 / 216.150.16.1), so this is genuinely first-party and Safari's
 * CNAME-cloaking rule does not apply either. One "Accept" now lasts the full six months.
 *
 * ── THIS IS NOT A TRUST BOUNDARY, AND IT MUST NOT BE MISTAKEN FOR ONE ───────────────
 *
 * `tc_consent` is deliberately NOT httpOnly — page JavaScript has to read it to decide
 * whether to inject a pixel, and a consent state the browser cannot read is one it
 * cannot honour (see `lib/consent.ts`). So the browser can already write this cookie
 * itself, and routing through here adds no authority whatsoever: it buys LONGEVITY and
 * nothing else. The body is validated only to keep a malformed value out of a cookie
 * that every later request has to parse.
 *
 * The client still writes the cookie itself first, so the banner closes and the pixels
 * react in the same frame. This call then rewrites the same value with a server-set
 * lifetime. If it fails, the visitor keeps the 7-day version — degraded, not broken.
 */
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));

  const analytics = body.analytics === true;
  const marketing = body.marketing === true;
  // The version the visitor actually answered against, as the banner displayed it.
  //
  // `typeof`, NOT `Number(...)`: `Number(null)` is 0, and 0 is the one integer that must
  // not be written here. `decodeConsent` refuses a cookie whose version is below the
  // current one, and a refused cookie reads as "has not answered" — so a stray `v: 0`
  // would re-ask this visitor on every page load, for ever. That is precisely the bug
  // this route exists to end, reintroduced by a lenient cast. Caught by the test.
  //
  // A visitor can only ever answer the version the banner showed them, which is
  // `MarketingSettings.consent_version` and is 1 or more; 0 means "no recorded version"
  // and is not something anyone can choose.
  const version = body.version;
  if (typeof version !== "number" || !Number.isInteger(version)
      || version < 1 || version > 2 ** 31) {
    return Response.json({ detail: "version must be an integer of 1 or more" }, { status: 400 });
  }

  // The SAME shape `encodeConsent` writes, because `decodeConsent` reads both and a
  // second spelling of this object would be a silent re-ask on the next page load.
  const value = JSON.stringify({ v: version, a: analytics ? 1 : 0, m: marketing ? 1 : 0 });

  (await cookies()).set(CONSENT_COOKIE, value, {
    httpOnly: false,
    sameSite: "lax",
    path: "/",
    maxAge: CONSENT_MAX_AGE,
    secure: process.env.NODE_ENV === "production",
  });

  return Response.json({ ok: true });
}
