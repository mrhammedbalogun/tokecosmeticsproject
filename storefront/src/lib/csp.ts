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

/** The media host is public and appears in every product page's HTML anyway. */
function mediaHost(): string {
  const host = process.env.NEXT_PUBLIC_MEDIA_HOST ?? "dk4ivng9pnc2t.cloudfront.net";
  return `https://${host}`;
}

/** The Django origin the browser talks to directly (client-side fetches). */
function apiOrigin(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
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
  ];

  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": scriptSrc,
    // Tailwind and Next both emit inline style attributes.
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:", "blob:", mediaHost()],
    "font-src": ["'self'", "data:"],
    "connect-src": ["'self'", apiOrigin(), ...PAYSTACK, ...PAYPAL, ...TURNSTILE],
    // The payment popups and the Turnstile challenge render in iframes.
    "frame-src": [...PAYSTACK, ...PAYPAL, ...TURNSTILE],
    // Nobody may frame us — clickjacking a checkout is the attack this stops, and it is
    // the CSP equivalent of the X-Frame-Options header already set on the API.
    "frame-ancestors": ["'none'"],
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
