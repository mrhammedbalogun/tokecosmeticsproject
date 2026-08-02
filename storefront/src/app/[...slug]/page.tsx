import { permanentRedirect, redirect, notFound } from "next/navigation";
import { getRedirect } from "@/lib/redirects";

/**
 * The root catch-all: legacy WordPress URLs (Plan-24).
 *
 * ── WHY THIS IS A CATCH-ALL AND NOT MIDDLEWARE ──────────────────────────────────────
 *
 * Next reaches this file only when no real route matched, because the App Router ranks
 * static and dynamic segments above catch-alls. That ordering is load-bearing rather than
 * incidental: WordPress served pages, posts and help articles from the root, and three of
 * those slugs are storefront routes today — `/account/` was a help article, `/search/`
 * and `/checkout/` were pages. Middleware consulting the redirect table on every request
 * would need a skip-list of every real route, and would send a signed-in customer from
 * their own account page to an article about accounts the first time somebody forgot to
 * update it. Here the precedence is a property of the framework.
 *
 * ── THIS ONLY WORKS BECAUSE THERE IS NO ROOT `app/loading.tsx` ──────────────────────
 *
 * A `loading.tsx` at the app root wraps everything in a Suspense boundary, which makes
 * Next commit the HTTP status before the body streams. Measured 2026-08-02: with one
 * present, `permanentRedirect()` here produced **200 with no Location header** — the
 * browser still followed the streamed client-side navigation, so it looked fine to a
 * human, while every crawler saw a 200. For a redirect layer whose entire purpose is
 * telling search engines a URL moved, that is a silent total failure. `notFound()` was
 * equally affected app-wide.
 *
 * The root loading.tsx was removed in Plan-25. The three routes that actually wanted a
 * skeleton keep their own. DO NOT ADD ONE BACK AT THE ROOT — `__tests__/no-root-loading`
 * fails if anybody does.
 *
 * ── ON 410 ──────────────────────────────────────────────────────────────────────────
 *
 * The table stores `410` for pages that were abandoned rather than moved. A Server
 * Component still cannot set an arbitrary status, so a 410 row renders the not-found page
 * and answers 404 — which it now genuinely does. The rows record the decision and stop
 * somebody later "fixing" those URLs with a redirect to the homepage. Search engines
 * de-index a 404 slightly slower than a 410 and otherwise treat them alike.
 */
export default async function LegacyUrlCatchAll({
  params,
}: {
  params: Promise<{ slug: string[] }>;
}) {
  const { slug } = await params;
  const path = `/${(slug ?? []).join("/")}`;

  const rule = await getRedirect(path);
  if (!rule || rule.status_code === 410) notFound();

  // `permanentRedirect` emits 308 and `redirect` 307 — the method-preserving pair. That is
  // correct for these: every legacy URL is a GET arriving from a link or a crawler, and
  // 308/307 tell a crawler the same thing 301/302 do about permanence.
  if (rule.status_code === 301) permanentRedirect(rule.new_path);
  redirect(rule.new_path);
}
