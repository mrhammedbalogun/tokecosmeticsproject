import type { Metadata } from "next";
import { PagePlaceholder } from "@/components/content/PagePlaceholder";
import { pageMetadata } from "@/lib/seo";

/** `/find-stores` — reached from the header's `More` menu (`lib/site-pages.ts`).
 *
 * A CODE ROUTE, NOT a CMS `/page/{slug}` entry: this page is getting a bespoke layout
 * once its copy is written, which sanitised HTML in `Page.body` cannot express. Replace
 * `PagePlaceholder` with the real thing; leave the metadata call in place. */
export const metadata: Metadata = pageMetadata({
  // BARE title. The root layout applies the `%s | Toke Cosmetics` template, so repeating
  // the brand here would render "Find Stores — Toke Cosmetics | Toke Cosmetics".
  title: "Find Stores",
  description:
    "Find a shop or pickup point stocking Toke Cosmetics near you.",
  path: "/find-stores",
});

export default function Page() {
  return (
    <PagePlaceholder
      title="Find Stores"
      intro="Every stockist and pickup point carrying Toke Cosmetics, with addresses and opening hours. The list is being compiled. Until it is here, we ship nationwide and worldwide."
    />
  );
}
