/**
 * Content-Security-Policy for the storefront (Plan-25 task 2).
 *
 * ── REPORT-ONLY FIRST, DELIBERATELY ─────────────────────────────────────────────────
 *
 * This policy is served as `Content-Security-Policy-Report-Only`. A CSP written against a
 * Next app with inline bootstrap script, a CMS that emits arbitrary published HTML, and
 * THREE third-party payment SDKs that inject their own scripts and iframes will block
 * something real on its first day. Shipping it enforcing means finding that out from a
 * customer who cannot pay. Report first, read what it would have blocked, then flip.
 *
 * The flip is a one-line change (`REPORT_ONLY = false`) plus the header name, and it is
 * gated on having actually read reports — not on this file looking finished.
 *
 * ── WHY EACH THIRD PARTY IS HERE ────────────────────────────────────────────────────
 *
 * Every origin below was found by reading the code, not by copying a starter policy:
 *
 *   js.paystack.co / checkout.paystack.com  `@paystack/inline-js` opens an inline popup —
 *                                           it injects a script and renders an iframe
 *   www.paypal.com / *.paypal.com           `PayPalScriptProvider` injects the PayPal SDK
 *                                           and renders buttons in iframes
 *   challenges.cloudflare.com               Turnstile, loaded by a hand-written script tag
 *                                           in TurnstileWidget.tsx and rendered in a frame
 *
 * Flutterwave is deliberately ABSENT: `FlutterwaveLaunch` does `window.location.assign`
 * to a hosted page, which is a top-level navigation and needs no CSP allowance. Stripe is
 * absent for the same reason — there is no Stripe SDK in `package.json`; the backend
 * gateway exists but the storefront hands off by redirect.
 *
 * The social links (facebook/instagram/tiktok) are anchors, not resources, so they need
 * nothing either.
 */

/** Flip to false ONLY after reading real reports. See the module docstring. */
export const REPORT_ONLY = true;

const PAYSTACK = ["https://js.paystack.co", "https://checkout.paystack.com"];
const PAYPAL = ["https://www.paypal.com", "https://*.paypal.com"];
const TURNSTILE = ["https://challenges.cloudflare.com"];
// Google Maps JS (Plan-32b slice 3: Places autocomplete + confirm-your-pin map),
// loaded by lib/googleMaps.ts. The origins follow Google's own published CSP
// allowlist for the Maps JS API: the script and data calls hit maps.googleapis.com,
// raster tiles and marker sprites come from *.googleapis.com/*.gstatic.com, and the
// library injects a fonts.googleapis.com stylesheet (hence the style/font entries).
const GMAPS_SCRIPT = ["https://maps.googleapis.com"];
const GMAPS_IMG = ["https://*.googleapis.com", "https://*.gstatic.com"];
const GMAPS_CONNECT = ["https://maps.googleapis.com"];
const GMAPS_STYLE = ["https://fonts.googleapis.com"];
const GMAPS_FONT = ["https://fonts.gstatic.com"];

// ── AD PIXELS (Plan-44) ─────────────────────────────────────────────────────────────
//
// Added in the SAME commit as the tags that need them, and this is the point of the
// exercise rather than tidiness. The policy above is REPORT-ONLY: a pixel added without
// its origins would work perfectly, log violations nobody reads, and then die silently
// on the day someone flips `REPORT_ONLY = false`. By then the connection between the
// flip and "Facebook stopped reporting sales" is a week of debugging.
//
// Each list below was derived from the loader snippets in
// `components/consent/TrackingScripts.tsx`, not copied from a starter policy:
//
//   connect.facebook.net       the Meta pixel's own script (fbevents.js)
//   www.facebook.com           where fbq POSTs events, and its tracking pixel image
//   analytics.tiktok.com       the TikTok pixel script AND where ttq sends events
//   sc-static.net              Snapchat's scevent.min.js
//   tr.snapchat.com            where snaptr sends events (also the CAPI host, but that
//                              call is server-to-server and needs nothing here)
//   www.googletagmanager.com   gtag.js, for BOTH Google Ads and GA4
//   *.google-analytics.com     GA4 collection; `region1.` is the EU endpoint
//   *.analytics.google.com     GA4's newer collection hosts
//   googleads.g.doubleclick.net / www.googleadservices.com / www.google.com
//                              the Google Ads conversion ping, which hops between all
//                              three depending on the visitor's region and cookie state
//   td.doubleclick.net         the conversion-linker iframe Google Ads renders
//
// Nothing here is loaded unless the visitor has consented and the channel is switched on
// in the admin — but a CSP is a static document and cannot express that, so every origin
// a granted visitor could reach must be listed.
const META_PIXEL_SCRIPT = ["https://connect.facebook.net"];
const META_PIXEL_ENDPOINT = ["https://www.facebook.com"];
const TIKTOK_PIXEL = ["https://analytics.tiktok.com", "https://analytics-sg.tiktok.com"];
const SNAP_PIXEL_SCRIPT = ["https://sc-static.net"];
const SNAP_PIXEL_ENDPOINT = ["https://tr.snapchat.com"];
const GOOGLE_TAG_SCRIPT = ["https://www.googletagmanager.com"];
const GOOGLE_COLLECT = [
  "https://www.google-analytics.com",
  "https://region1.google-analytics.com",
  "https://*.analytics.google.com",
  "https://stats.g.doubleclick.net",
];
const GOOGLE_ADS_CONVERSION = [
  "https://googleads.g.doubleclick.net",
  "https://www.googleadservices.com",
  "https://www.google.com",
];

const PIXEL_SCRIPT = [
  ...META_PIXEL_SCRIPT, ...TIKTOK_PIXEL, ...SNAP_PIXEL_SCRIPT, ...GOOGLE_TAG_SCRIPT,
];
const PIXEL_CONNECT = [
  ...META_PIXEL_ENDPOINT, ...TIKTOK_PIXEL, ...SNAP_PIXEL_ENDPOINT,
  ...GOOGLE_COLLECT, ...GOOGLE_ADS_CONVERSION,
];
// Several of these still fall back to a 1x1 GIF when a fetch/beacon is blocked, so the
// image list is not a subset of the connect list by accident — it is the fallback path.
const PIXEL_IMG = [
  ...META_PIXEL_ENDPOINT, ...TIKTOK_PIXEL, ...SNAP_PIXEL_ENDPOINT,
  ...GOOGLE_COLLECT, ...GOOGLE_ADS_CONVERSION,
];
// Google Ads' conversion linker renders an iframe; Meta's pixel occasionally does too.
const PIXEL_FRAME = ["https://td.doubleclick.net", ...META_PIXEL_ENDPOINT];

/** The media host is public and appears in every product page's HTML anyway. */
function mediaHost(): string {
  const host = process.env.NEXT_PUBLIC_MEDIA_HOST ?? "dk4ivng9pnc2t.cloudfront.net";
  return `https://${host}`;
}

/** The Django origin the browser talks to directly (client-side fetches). */
function apiOrigin(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

/** The admin app, which frames the storefront for its live homepage preview. */
function adminOrigin(dev: boolean): string {
  return (
    process.env.NEXT_PUBLIC_ADMIN_ORIGIN ??
    (dev ? "http://localhost:3001" : "https://admin.tokecosmetics.com")
  );
}

/**
 * Who may frame the storefront: nobody but ourselves and the admin's live preview.
 *
 * Served as its own ENFORCED Content-Security-Policy header (next.config.ts) even while
 * the full policy above stays report-only: framing protection existed before this file
 * (X-Frame-Options) and must not regress to report-only just because the admin preview
 * needs a carve-out. Browsers that enforce frame-ancestors ignore X-Frame-Options, which
 * is what lets the carve-out work while the legacy DENY header stays on.
 */
export function frameAncestorsPolicy({ dev = false }: { dev?: boolean } = {}): string {
  return `frame-ancestors 'self' ${adminOrigin(dev)}`;
}

export function buildCsp({ dev = false }: { dev?: boolean } = {}): string {
  const scriptSrc = [
    "'self'",
    // Next's bootstrap and streamed RSC payload are inline. Removing this needs
    // per-request nonces, which needs the policy to move into proxy.ts — a real option
    // once report-only has proven the rest of the policy is right.
    "'unsafe-inline'",
    // Dev only: Turbopack's HMR client evaluates code. NEVER in production.
    ...(dev ? ["'unsafe-eval'"] : []),
    ...PAYSTACK,
    ...PAYPAL,
    ...TURNSTILE,
    ...GMAPS_SCRIPT,
    ...PIXEL_SCRIPT,
  ];

  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": scriptSrc,
    // Tailwind and Next both emit inline style attributes.
    "style-src": ["'self'", "'unsafe-inline'", ...GMAPS_STYLE],
    "img-src": ["'self'", "data:", "blob:", mediaHost(), ...GMAPS_IMG, ...PIXEL_IMG],
    // Product videos play straight off CloudFront (ProductVideos.tsx). Without an
    // explicit media-src the browser falls back to default-src 'self', which would
    // block every one of them the day this policy stops being report-only. apiOrigin
    // covers dev, where Django serves /media itself.
    "media-src": ["'self'", mediaHost(), apiOrigin()],
    "font-src": ["'self'", "data:", ...GMAPS_FONT],
    "connect-src": [
      "'self'", apiOrigin(), ...PAYSTACK, ...PAYPAL, ...TURNSTILE, ...GMAPS_CONNECT,
      ...PIXEL_CONNECT,
    ],
    // The payment popups and the Turnstile challenge render in iframes.
    "frame-src": [...PAYSTACK, ...PAYPAL, ...TURNSTILE, ...PIXEL_FRAME],
    // Clickjacking a checkout is the attack this stops. 'self' plus the admin app only —
    // the admin frames the storefront for its live homepage preview; see
    // frameAncestorsPolicy below, which is the ENFORCED copy of this directive.
    "frame-ancestors": ["'self'", adminOrigin(dev)],
    "base-uri": ["'self'"],
    // A CMS body is sanitised on write, but a <form> that survived would post wherever it
    // liked. This is the second layer that makes that harmless.
    "form-action": ["'self'"],
    "object-src": ["'none'"],
  };

  return Object.entries(directives)
    .map(([key, values]) => `${key} ${values.join(" ")}`)
    .join("; ");
}

export const CSP_HEADER_NAME = REPORT_ONLY
  ? "Content-Security-Policy-Report-Only"
  : "Content-Security-Policy";
