/**
 * Content-Security-Policy for the admin (Plan-25 task 2).
 *
 * ── ENFORCED HERE, REPORT-ONLY ON THE STOREFRONT ────────────────────────────────────
 *
 * The asymmetry is the point. The storefront renders CMS bodies authored as WordPress and
 * Elementor markup, and loads three third-party payment SDKs that inject their own
 * scripts and iframes — a policy written blind against that will block something real, so
 * it reports first. The admin has none of that: four dependencies (`next`, `react`,
 * `react-dom`, `uqr`), no payment SDK, no third-party content, and every byte it renders
 * is ours. There is nothing here to discover by watching reports, and the admin is the
 * higher-value target — it holds every customer's PII and the order desk.
 *
 * Turnstile is the single external SCRIPT origin, and only on the staff login page.
 * The storefront appears in `frame-src` alone — /home-content frames the live shop as
 * its preview (2026-08-06). A frame is not a script: nothing from the storefront runs
 * on this origin, so the zero-third-party-scripts rule stands.
 *
 * `uqr` renders the TOTP enrolment QR code, and renders it as an inline SVG rather than
 * fetching an image — which is why no external image host appears below.
 */

const TURNSTILE = ["https://challenges.cloudflare.com"];

/** The storefront /home-content frames as its live preview. Kept in lockstep with
 *  `storefrontUrl()` in lib/env.ts (imported would be nicer, but this file must stay
 *  importable from next.config.ts without dragging app code in). */
function storefrontOrigin(): string {
  return process.env.NEXT_PUBLIC_STOREFRONT_URL ?? "http://localhost:3000";
}

/** The host catalogue and banner images are served from — in `img-src` since Plan-17a,
 *  because without it every product and homepage thumbnail renders broken and the only
 *  evidence is a CSP violation in the console. Committed as a default rather than left
 *  to a dashboard entry: the CDN hostname is public (it is in every product page's
 *  HTML), and a missing env var breaking every production image is not hypothetical —
 *  it is what happened to the storefront. `NEXT_PUBLIC_MEDIA_HOST` still overrides. */
function mediaHost(): string {
  return `https://${process.env.NEXT_PUBLIC_MEDIA_HOST ?? "dk4ivng9pnc2t.cloudfront.net"}`;
}

/** The Django origin the browser talks to directly. The BFF proxies most calls, but the
 *  value is public either way — it is in the page source. */
function apiOrigin(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

export function buildCsp({ dev = false }: { dev?: boolean } = {}): string {
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": [
      "'self'",
      // Next's bootstrap and streamed RSC payload are inline. Nonces would remove this
      // and are the natural next step once the policy has proven itself in production.
      "'unsafe-inline'",
      // Turbopack HMR only. NEVER in production.
      ...(dev ? ["'unsafe-eval'"] : []),
      ...TURNSTILE,
    ],
    "style-src": ["'self'", "'unsafe-inline'"],
    // `data:` covers the inline QR for TOTP enrolment; the media host covers catalogue
    // and homepage-banner thumbnails, which the admin absolutely does render. The API
    // origin is here for dev, where Django serves uploads itself (/media/…) — in
    // production it serves none, so the entry is inert.
    "img-src": ["'self'", "data:", "blob:", mediaHost(), apiOrigin()],
    "font-src": ["'self'", "data:"],
    "connect-src": ["'self'", apiOrigin(), ...TURNSTILE],
    "frame-src": [...TURNSTILE, storefrontOrigin()],
    "frame-ancestors": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "object-src": ["'none'"],
  };

  return Object.entries(directives)
    .map(([key, values]) => `${key} ${values.join(" ")}`)
    .join("; ");
}

export const CSP_HEADER_NAME = "Content-Security-Policy";
