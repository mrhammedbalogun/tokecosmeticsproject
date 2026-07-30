import type { NextConfig } from "next";

/**
 * ── ADMIN ORIGIN HARDENING (Plan-16 Amendment 4) ───────────────────────────────────
 *
 * The load-bearing boundary is the API's RBAC plus the staff auth ceremony; this origin
 * is a shell that should hold nothing secret. What is cheap and worth doing anyway:
 *
 * - `X-Robots-Tag: noindex` site-wide, and no sitemap. The storefront must never link
 *   here either. This is not a security control — obscurity never is — it just keeps the
 *   hostname out of the places that publish hostnames.
 * - No framing, no referrer leakage, no MIME sniffing.
 * - `Cache-Control: no-store` on every page and BFF response. It is set in BOTH places and
 *   that is not redundancy for its own sake: `src/proxy.ts` covers redirects and BFF
 *   routes, but Next OVERWRITES Cache-Control on a rendered page response after the proxy
 *   runs (measured: `/login` came back `no-cache, must-revalidate`, which permits storing
 *   the page — only revalidating it). A `headers()` entry wins that argument. The source
 *   pattern excludes `_next/static`, whose immutable chunks should stay cacheable: chunks
 *   contain no PII, pages do.
 *
 * ── ZERO THIRD-PARTY SCRIPTS ON THIS ORIGIN. EVER. ─────────────────────────────────
 *
 * No analytics, no tag manager, no session replay, no error-reporting snippet, no font
 * CDN. This is a standing rule, not a preference, and it is what makes two things in this
 * app safe that would otherwise not be:
 *
 *  - `/accept-invite?token=…` puts a staff-creation capability in a URL. A URL is read by
 *    every script on the page (`location.href`), and a third-party script is a third
 *    party reading it. With none, the token's exposure is the recipient's inbox and their
 *    own browser history — which is the exposure the backend already accepts.
 *  - The TOTP setup screen renders a secret. Same argument, higher stakes.
 *
 * The one exception is Cloudflare Turnstile's own widget script, which is required for the
 * gate to function and is loaded only on the two unauthenticated forms. It is not
 * analytics, and it never runs on a page that holds an admin session.
 *
 * The CSP below is the enforcement, so the rule survives a contributor who has not read
 * this comment.
 */
const isProd = process.env.NODE_ENV === "production";

/**
 * The origin catalogue images are served from — CloudFront in production, and whatever
 * `AWS_S3_CUSTOM_DOMAIN` resolves to elsewhere. Added to `img-src` in Plan-17a Task 2,
 * because without it the products list renders every thumbnail as a broken image and the
 * only evidence is a CSP violation in the console.
 *
 * ORIGIN ONLY, never a wildcard. This widens exactly one directive, for images, to one
 * host we control. It does NOT touch `script-src` or `connect-src`, and the standing rule
 * above — no third-party scripts on this origin, ever — is untouched by it: an image
 * cannot read `location.href`, and `object-src 'none'` still forbids the plugin content
 * types that could.
 *
 * Empty in local dev, where media is served from the Django origin through the BFF and
 * `'self'` already covers it. Set `NEXT_PUBLIC_MEDIA_ORIGIN` in the Vercel project to the
 * CloudFront hostname, matching the backend's `AWS_S3_CUSTOM_DOMAIN`.
 */
const MEDIA_ORIGIN = process.env.NEXT_PUBLIC_MEDIA_ORIGIN ?? "";

const CSP = [
  "default-src 'self'",
  // Next's App Router requires inline bootstrap scripts. `unsafe-eval` is dev-only (React
  // Refresh needs it); production gets neither it nor any host but Turnstile's.
  `script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com${isProd ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' data: blob:${MEDIA_ORIGIN ? ` ${MEDIA_ORIGIN}` : ""}`,
  "font-src 'self' data:",
  // Same-origin only: every API call goes through this app's own BFF routes or its Server
  // Functions, never straight from the browser to Django. `ws:` is Next's dev HMR socket.
  `connect-src 'self'${isProd ? "" : " ws: wss:"}`,
  "frame-src https://challenges.cloudflare.com",
  "frame-ancestors 'none'",
  "form-action 'self'",
  "base-uri 'self'",
  "object-src 'none'",
].join("; ");

const NO_STORE = {
  key: "Cache-Control",
  value: "no-store, no-cache, must-revalidate, private",
};

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Robots-Tag", value: "noindex, nofollow, noarchive, nosnippet" },
          { key: "Content-Security-Policy", value: CSP },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
      // Two entries because a single `/:path(<regex>)` source requires at least one
      // segment and so never matches "/". Both exclude `_next/static`: its chunks are
      // content-hashed and immutable, they contain no PII, and blanket-no-storing them
      // makes every hard page load re-download the whole bundle for nothing.
      { source: "/", headers: [NO_STORE] },
      { source: "/:path((?!_next/static/|_next/image).*)", headers: [NO_STORE] },
    ];
  },
};

export default nextConfig;
