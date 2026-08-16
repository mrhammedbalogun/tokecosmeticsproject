import type { Metadata } from "next";
import { PagePlaceholder } from "@/components/content/PagePlaceholder";
import { pageMetadata } from "@/lib/seo";

/** `/affiliates` — reached from the header's `More` menu (`lib/site-pages.ts`).
 *
 * A CODE ROUTE, NOT a CMS `/page/{slug}` entry: this page is getting a bespoke layout
 * once its copy is written, which sanitised HTML in `Page.body` cannot express. Replace
 * `PagePlaceholder` with the real thing; leave the metadata call in place. */
export const metadata: Metadata = pageMetadata({
  // BARE title. The root layout applies the `%s | Toke Cosmetics` template, so repeating
  // the brand here would render "Affiliates — Toke Cosmetics | Toke Cosmetics".
  title: "Affiliates",
  description:
    "Earn commission promoting Toke Cosmetics. Programme terms and commission tiers.",
  path: "/affiliates",
});

export default function Page() {
  return (
    <PagePlaceholder
      title="Affiliates"
      intro="Earn on every sale you send our way. Our referral programme is already live inside your account — the full affiliate terms and commission tiers land on this page next."
      ctaHref="/account/referrals"
      ctaLabel="Go to my referrals"
    />
  );
}
