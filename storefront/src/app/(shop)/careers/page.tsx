import type { Metadata } from "next";
import { PagePlaceholder } from "@/components/content/PagePlaceholder";
import { pageMetadata } from "@/lib/seo";

/** `/careers` — reached from the header's `More` menu (`lib/site-pages.ts`).
 *
 * A CODE ROUTE, NOT a CMS `/page/{slug}` entry: this page is getting a bespoke layout
 * once its copy is written, which sanitised HTML in `Page.body` cannot express. Replace
 * `PagePlaceholder` with the real thing; leave the metadata call in place. */
export const metadata: Metadata = pageMetadata({
  // BARE title. The root layout applies the `%s | Toke Cosmetics` template, so repeating
  // the brand here would render "Careers — Toke Cosmetics | Toke Cosmetics".
  title: "Careers",
  description:
    "Work at Toke Cosmetics. Open roles across formulation, fulfilment, retail and customer care.",
  path: "/careers",
});

export default function Page() {
  return (
    <PagePlaceholder
      title="Careers"
      intro="Open roles at Toke Cosmetics — formulation, fulfilment, retail and customer care — will be posted on this page as they come up."
    />
  );
}
