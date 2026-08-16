import type { Metadata } from "next";
import { PagePlaceholder } from "@/components/content/PagePlaceholder";
import { pageMetadata } from "@/lib/seo";

/** `/entrepreneurial-program` — reached from the header's `More` menu (`lib/site-pages.ts`).
 *
 * A CODE ROUTE, NOT a CMS `/page/{slug}` entry: this page is getting a bespoke layout
 * once its copy is written, which sanitised HTML in `Page.body` cannot express. Replace
 * `PagePlaceholder` with the real thing; leave the metadata call in place. */
export const metadata: Metadata = pageMetadata({
  // BARE title. The root layout applies the `%s | Toke Cosmetics` template, so repeating
  // the brand here would render "Entrepreneurial Program — Toke Cosmetics | Toke Cosmetics".
  title: "Entrepreneurial Program",
  description:
    "Build a business reselling Toke Cosmetics — pricing tiers, minimum orders and training.",
  path: "/entrepreneurial-program",
});

export default function Page() {
  return (
    <PagePlaceholder
      title="Entrepreneurial Program"
      intro="Our programme for resellers and distributors who want to build a business on Toke Cosmetics — pricing tiers, minimum orders and training. Details are being finalised."
    />
  );
}
