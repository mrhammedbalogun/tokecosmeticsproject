import type { NextConfig } from "next";
import { CSP_HEADER_NAME, REPORT_ONLY, buildCsp, frameAncestorsPolicy } from "./src/lib/csp";

// ── RETIRED CATEGORY URLS (the Shop by Category rework, 2026-09-10) ────────────────────
//
// `manage.py rebuild_shop_menu` renamed some categories and merged others away, so slugs
// that Google has indexed no longer resolve. `core.Redirect` — the table that handles
// every other legacy URL — cannot serve these: it is read by the ROOT catch-all
// (`app/[...slug]`), and `/category/[slug]` is a real route that renders notFound()
// long before any catch-all is reached.
//
// ONLY GENUINE EQUIVALENTS ARE LISTED. "Men Care" and "Skincare Sets" left the menu with
// no successor, and pointing them at /products would be a soft 404 — Google treats a
// redirect to an unrelated page as one, and a shopper following an old link to a shelf
// that no longer exists is better served by an honest 404 than by being dropped into the
// full catalogue. Those simply 404.
const LEGACY_CATEGORY_REDIRECTS = [
  // Renamed in place: the row kept its products and took a new slug.
  ["baby-care", "/category/baby-kids-care"],
  ["facials", "/category/facial-care"],
  ["travel-size", "/category/travel-sizes"],
  ["shop-by-skin-concern", "/category/shop-by-skin-concerns"],
  // Merged away: duplicates whose products moved onto the row that survived.
  ["baby-care-shop-by-category", "/category/baby-kids-care"],
  ["kids", "/category/baby-kids-care"],
  ["kids-care", "/category/baby-kids-care"],
  ["hair-care-shop-by-category", "/category/hair-care"],
  ["skin-care-2", "/category/skin-care"],
  ["facial-set", "/category/facial-care"],
  ["travel-size-shop-by-category", "/category/travel-sizes"],
  ["travel-size-shop-by-edit", "/category/travel-sizes"],
  // The old WordPress "shop by edit" categories, now computed listings of their own.
  ["best-sellers", "/best-sellers"],
  ["new-arrivals", "/new-arrivals"],
  ["promo", "/promo"],
  ["promo-2", "/promo"],
  ["combo-Deals", "/combo"],
  ["shop-all", "/products"],
].map(([slug, destination]) => ({
  source: `/category/${slug}`,
  destination,
  permanent: true,
}));

const nextConfig: NextConfig = {
  // ── LEGACY WORDPRESS MEDIA ────────────────────────────────────────────────────────
  //
  // The Plan-24 content import brings WordPress page and post bodies across as HTML, and
  // `cms.sanitize`'s allow-list keeps `<img src>` absolute. Those sources are all
  // `https://tokecosmetics.com/wp-content/uploads/...` — which resolves to WordPress
  // today and to this app the moment the root domain cuts over, at which point every
  // image inside 47 imported pages becomes a 404.
  //
  // The redirect table cannot do this: `core.Redirect` matches exact paths and the
  // Plan-24 map only ever emits rows for pages, posts, help articles, categories and
  // tags. Rewriting the stored HTML instead would mean editing 47 sanitised bodies and
  // getting it right for every future import; one prefix rule covers all of them, and
  // keeps working for any old blog post somebody links to years from now.
  //
  // Points at `old.` because that is where the uploads directory physically stays after
  // the cutover — the files are not copied anywhere, the vhost simply changes name.
  async redirects() {
    return [
      {
        source: "/wp-content/:path*",
        destination: "https://old.tokecosmetics.com/wp-content/:path*",
        permanent: true,
      },
      ...LEGACY_CATEGORY_REDIRECTS,
    ];
  },
  images: {
    // Backend media (seeded product/category images) in dev, plus the production media
    // CDN when one is configured.
    //
    // Production images live in a PRIVATE S3 bucket and are served through CloudFront
    // with Origin Access Control. The bucket stays private on purpose: the nightly
    // Postgres backups share it (`backups/` alongside `catalog/`, see
    // infra/deploy/backup.sh), so granting public read would mean switching off Block
    // Public Access on the bucket that holds the database dumps. See docs/architecture.md.
    //
    // The CDN hostname is a PUBLIC value (it appears in every product page's HTML), so
    // it is committed as the default rather than living only in a Vercel env var —
    // the env var still overrides it (e.g. pointing previews at a different
    // distribution), but a missing dashboard entry can no longer break every product
    // image in production, which is exactly what happened before this default existed.
    remotePatterns: [
      { protocol: "http", hostname: "localhost", port: "8000", pathname: "/media/**" },
      {
        protocol: "https" as const,
        hostname: process.env.NEXT_PUBLIC_MEDIA_HOST ?? "dk4ivng9pnc2t.cloudfront.net",
        // `/catalog/**`, never `/**`: the optimizer must refuse to proxy anything
        // but catalog media even if another prefix ever becomes reachable.
        pathname: "/catalog/**",
      },
    ],
    // Next 16 breaking change (version-16.md § "Local IP Restriction"): the image
    // optimizer refuses to fetch upstreams that resolve to a private/loopback IP.
    // Our dev backend serves /media from localhost (127.0.0.1/::1), so seeded
    // catalog images 400 without this. GATED to development only — in production
    // the SSRF guard must stay ON (defense-in-depth against DNS-rebinding /
    // internal-IP fetch through a remotePatterns-allowed host once Plan-22 adds a
    // remote media origin). NODE_ENV is "development" under `npm run dev`.
    dangerouslyAllowLocalIP: process.env.NODE_ENV !== "production",
    // Local, self-authored SVG art only (public/home/**, generated by
    // scripts/gen-placeholders.mjs). NEVER feed user-supplied or remote SVGs
    // through the optimizer — the CSP sandbox below is the backstop.
    dangerouslyAllowSVG: true,
    contentSecurityPolicy: "default-src 'self'; script-src 'none'; sandbox;",
  },
};

/**
 * Security headers (Plan-25 task 2).
 *
 * CSP is REPORT-ONLY on the storefront — see `src/lib/csp.ts` for why, and for the list
 * of third-party payment origins it had to be built around. The API's own headers
 * (HSTS, nosniff, X-Frame-Options) are set by Django on `api.` and are not duplicated
 * here; these apply to the pages the browser actually renders.
 */
nextConfig.headers = async () => [
  {
    source: "/:path*",
    headers: [
      { key: CSP_HEADER_NAME, value: buildCsp({ dev: process.env.NODE_ENV !== "production" }) },
      // Framing protection is ENFORCED even while the full policy is report-only: this
      // minimal policy carries only frame-ancestors ('self' + the admin's live preview).
      // Skipped once the full policy enforces — Next's headers() would collapse two
      // same-key entries, and the full policy carries the same directive by then.
      ...(REPORT_ONLY
        ? [
            {
              key: "Content-Security-Policy",
              value: frameAncestorsPolicy({ dev: process.env.NODE_ENV !== "production" }),
            },
          ]
        : []),
      // Belt and braces for browsers that predate frame-ancestors; anything modern
      // ignores this header when an enforced frame-ancestors is present.
      { key: "X-Frame-Options", value: "DENY" },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      // The storefront needs none of these. Naming them is what stops a future dependency
      // quietly asking the customer for their camera on a checkout page.
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
    ],
  },
];

export default nextConfig;
