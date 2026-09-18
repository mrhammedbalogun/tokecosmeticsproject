import type { Metadata } from "next";
import { PagePlaceholder } from "@/components/content/PagePlaceholder";
import { pageMetadata } from "@/lib/seo";

/** `/disclaimer` — reached from the header's `More` menu (`lib/site-pages.ts`).
 *
 * A CODE ROUTE, NOT a CMS `/page/{slug}` entry: this page is getting a bespoke layout
 * once its copy is written, which sanitised HTML in `Page.body` cannot express. Replace
 * `PagePlaceholder` with the real thing; leave the metadata call in place. */
export const metadata: Metadata = pageMetadata({
  // BARE title. The root layout applies the `%s | Toke Cosmetics` template, so repeating
  // the brand here would render "Disclaimer — Toke Cosmetics | Toke Cosmetics".
  title: "Disclaimer",
  description:
    "Product claims, ingredient information and results disclaimer for Toke Cosmetics.",
  path: "/disclaimer",
});

export default function Page() {
  return (
    <PagePlaceholder
      title="Disclaimer"
      intro="The terms covering product claims, ingredient information and results shown on this site. This notice is being prepared alongside our privacy policy and terms."
    />
  );
}
