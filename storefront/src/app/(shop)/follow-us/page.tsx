import type { Metadata } from "next";
import { PagePlaceholder } from "@/components/content/PagePlaceholder";
import { pageMetadata } from "@/lib/seo";

/** `/follow-us` — reached from the header's `More` menu (`lib/site-pages.ts`).
 *
 * A CODE ROUTE, NOT a CMS `/page/{slug}` entry: this page is getting a bespoke layout
 * once its copy is written, which sanitised HTML in `Page.body` cannot express. Replace
 * `PagePlaceholder` with the real thing; leave the metadata call in place. */
export const metadata: Metadata = pageMetadata({
  // BARE title. The root layout applies the `%s | Toke Cosmetics` template, so repeating
  // the brand here would render "Follow Us — Toke Cosmetics | Toke Cosmetics".
  title: "Follow Us",
  description:
    "Follow Toke Cosmetics on Instagram, Facebook and TikTok, and join our mailing list.",
  path: "/follow-us",
});

export default function Page() {
  return (
    <PagePlaceholder
      title="Follow Us"
      intro="Everywhere you can find Toke Cosmetics — Instagram, Facebook, TikTok and our mailing list — gathered in one place. Until this page is filled in, every link lives in the footer below."
    />
  );
}
