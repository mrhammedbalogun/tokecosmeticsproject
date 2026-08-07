import type { NextConfig } from "next";
import { CSP_HEADER_NAME, buildCsp } from "./src/lib/csp";

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
const NO_STORE = {
  key: "Cache-Control",
  value: "no-store, no-cache, must-revalidate, private",
};

/**
 * Security headers (Plan-25 task 2; merged 2026-08-06). CSP is ENFORCED here, unlike
 * the storefront — see `src/lib/csp.ts` for why the two differ, and for the media-host
 * and storefront-preview allowances the policy carries.
 *
 * ONE headers() ONLY. This file briefly held two — a `nextConfig.headers = ...`
 * assignment silently overwrote the object-literal one, which cost the app its
 * `Cache-Control: no-store` pages and its media-host img-src for a while. If you need
 * to change headers, change them HERE.
 */
const nextConfig: NextConfig = {
  // Server actions default to a 1MB request-body cap, which silently rejected any
  // banner/product media upload bigger than that (the modal hung on "Saving…" —
  // 2026-08-07). 85mb covers the 80MB video guard in uploadBannerMediaAction plus
  // multipart overhead. NOTE: Vercel's platform still caps function request bodies
  // (~4.5MB), so this ceiling is only reachable when self-hosting; the upload UI
  // downscales images client-side to stay under the platform cap.
  experimental: {
    serverActions: { bodySizeLimit: "85mb" },
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: CSP_HEADER_NAME, value: buildCsp({ dev: process.env.NODE_ENV !== "production" }) },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          // The admin must never leak a customer's Toke ID or an order number into a
          // third-party referer header.
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          // The admin has no business being indexed, and the staff login page is the one
          // URL an attacker would look for first.
          { key: "X-Robots-Tag", value: "noindex, nofollow, noarchive, nosnippet" },
        ],
      },
      // Pages hold PII, so they are never stored (see the hardening comment above —
      // `src/proxy.ts` alone loses to Next's own Cache-Control on rendered pages). Two
      // entries because a single `/:path(<regex>)` source requires at least one segment
      // and so never matches "/". Both exclude `_next/static` + `_next/image`: those are
      // content-hashed, PII-free, and no-storing them re-downloads the bundle for nothing.
      { source: "/", headers: [NO_STORE] },
      { source: "/:path((?!_next/static/|_next/image).*)", headers: [NO_STORE] },
    ];
  },
};

export default nextConfig;
