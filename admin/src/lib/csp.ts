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
 * Turnstile is the single external origin, and only on the staff login page.
 *
 * `uqr` renders the TOTP enrolment QR code, and renders it as an inline SVG rather than
 * fetching an image — which is why no external image host appears below.
 */

const TURNSTILE = ["https://challenges.cloudflare.com"];

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
    // `data:` covers the inline QR for TOTP enrolment; no remote image host is needed
    // because the admin renders no customer or catalogue imagery.
    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'", "data:"],
    "connect-src": ["'self'", apiOrigin(), ...TURNSTILE],
    "frame-src": TURNSTILE,
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
