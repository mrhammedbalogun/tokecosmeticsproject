import type { Metadata } from "next";
import { PagePlaceholder } from "@/components/content/PagePlaceholder";
import { pageMetadata } from "@/lib/seo";

/** `/contact-us` — reached from the header's `More` menu (`lib/site-pages.ts`).
 *
 * A CODE ROUTE, NOT a CMS `/page/{slug}` entry: this page is getting a bespoke layout
 * once its copy is written, which sanitised HTML in `Page.body` cannot express. Replace
 * `PagePlaceholder` with the real thing; leave the metadata call in place. */
export const metadata: Metadata = pageMetadata({
  // BARE title. The root layout applies the `%s | Toke Cosmetics` template, so repeating
  // the brand here would render "Contact Us — Toke Cosmetics | Toke Cosmetics".
  title: "Contact Us",
  description:
    "Get in touch with Toke Cosmetics — customer care, order enquiries and wholesale.",
  path: "/contact-us",
});

export default function Page() {
  return (
    <PagePlaceholder
      title="Contact Us"
      intro="Our phone, email and WhatsApp lines are being published here shortly. In the meantime the fastest reply is a direct message on Instagram, TikTok or Facebook — every link is in the footer below."
      ctaHref="/account/orders"
      ctaLabel="Track an order"
    />
  );
}
