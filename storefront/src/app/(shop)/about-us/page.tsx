import type { Metadata } from "next";
import { PagePlaceholder } from "@/components/content/PagePlaceholder";
import { pageMetadata } from "@/lib/seo";

/** `/about-us` — reached from the header's `More` menu (`lib/site-pages.ts`).
 *
 * A CODE ROUTE, NOT a CMS `/page/{slug}` entry: this page is getting a bespoke layout
 * once its copy is written, which sanitised HTML in `Page.body` cannot express. Replace
 * `PagePlaceholder` with the real thing; leave the metadata call in place. */
export const metadata: Metadata = pageMetadata({
  // BARE title. The root layout applies the `%s | Toke Cosmetics` template, so repeating
  // the brand here would render "About Us — Toke Cosmetics | Toke Cosmetics".
  title: "About Us",
  description:
    "The story behind Toke Cosmetics: who we are, how we formulate, and why we build skincare for melanin-rich skin.",
  path: "/about-us",
});

export default function Page() {
  return (
    <PagePlaceholder
      title="About Us"
      intro="How Toke Cosmetics started, who formulates our products, and why every one of them is built for melanin-rich skin. The full story is being written."
    />
  );
}
