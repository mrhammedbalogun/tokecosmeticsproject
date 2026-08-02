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
 * ── ON 410 ──────────────────────────────────────────────────────────────────────────
 *
 * The table stores `410` for pages that were abandoned rather than moved. This route
 * cannot honour it: a Server Component cannot set an arbitrary HTTP status, and a Route
 * Handler that could would have to return a bare response instead of the styled 404 page.
 * So a 410 row renders the ordinary not-found page and answers 404. The rows are still
 * worth keeping — they record the decision, and stop somebody later "fixing" those URLs
 * with a redirect to the homepage — but they are documentation, not behaviour. Search
 * engines de-index a 404 slightly slower than a 410 and otherwise treat them alike.
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
