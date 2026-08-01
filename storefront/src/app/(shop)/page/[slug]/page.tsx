import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getPage } from "@/lib/cms";
import { pageMetadata } from "@/lib/seo";

/**
 * `/page/{slug}` — CMS content (Plan-19a).
 *
 * ── THIS ROUTE USED TO ANSWER 200 FOR EVERYTHING ────────────────────────────────────
 *
 * It rendered the slug as a heading and the sentence "CMS content arrives in Plan-19",
 * for ANY slug — so `/page/asdf` was an indexable page, and the eleven real links in the
 * footer all led to the name of an internal plan. Unknown slugs now `notFound()`.
 *
 * ── THE STATUS IS 200, AND THAT IS THE APP, NOT THIS ROUTE ──────────────────────────
 *
 * Measured: `/page/asdf` renders the not-found UI but answers **HTTP 200**. `app/loading.tsx`
 * is a root Suspense boundary, so every route in this storefront commits to 200 before the
 * body streams, and Next cannot revise the status afterwards — its own streaming guide says
 * so, and injects `<meta name="robots" content="noindex">` instead (verified present here).
 * A nonexistent PRODUCT behaves identically, so this predates Plan-19 and is a property of
 * the whole app.
 *
 * Per Next's guidance a noindex soft-404 does not get indexed, so the SEO problem is
 * covered; what is lost is a truthful status code for crawlers and analytics. Fixing that
 * needs an existence check before the stream starts (proxy-level), which is an app-wide
 * decision and belongs with Plan-25's SEO pass, not here.
 *
 * A DRAFT IS ALSO A 404, because the API answers 404 for one (the existence of an
 * unpublished page is not public information) and nothing here should paper over that.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const page = await getPage(slug).catch(() => null);
  if (!page) {
    return pageMetadata({ title: "Not found", description: "", path: `/page/${slug}` });
  }
  return pageMetadata({
    // The SEO fields fall back to the page's own title/description rather than being
    // required — an editor should not have to fill three boxes to publish a policy.
    title: page.seo_title || page.title,
    description: page.seo_description || page.title,
    path: `/page/${slug}`,
  });
}

export default async function CmsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const page = await getPage(slug);
  if (!page) notFound();

  return (
    <article className="mx-auto max-w-3xl px-4 py-16">
      <h1 className="font-display text-4xl">{page.title}</h1>
      {/* SANITISED SERVER-SIDE ON WRITE (`apps/cms/sanitize.py`), never here: the database
          holds only allow-listed HTML, so every reader is safe without repeating the rule.
          This is the one place a Content editor's markup reaches a customer's browser. */}
      <div
        className="prose prose-sm mt-8 max-w-none leading-relaxed text-muted"
        dangerouslySetInnerHTML={{ __html: page.body }}
      />
    </article>
  );
}
