import type { Metadata } from "next";
import { PagePlaceholder } from "@/components/content/PagePlaceholder";
import { pageMetadata } from "@/lib/seo";

/** `/blog` — reached from the header's `More` menu (`lib/site-pages.ts`).
 *
 * Was a top-level nav item until 2026-08-16; it now sits inside `More` alongside the
 * other supporting pages. The route did not move, so every existing link still works.
 *
 * Placeholder until The Journal is built. Converted to the shared `PagePlaceholder`
 * (2026-08-16) — this page and `/skin-quiz` held two hand-rolled copies of the same
 * markup that had already drifted in wording. */
export const metadata: Metadata = pageMetadata({
  // BARE title — the root layout appends " | Toke Cosmetics". This page used to declare
  // "The Journal — Toke Cosmetics" and therefore rendered the brand twice.
  title: "The Journal",
  description:
    "Skincare guides, ingredient explainers and routines from Toke Cosmetics.",
  path: "/blog",
});

export default function Page() {
  return (
    <PagePlaceholder
      title="The Journal"
      intro="Skincare guides, ingredient explainers and routines from the people who formulate our products. We are putting the finishing touches on this — in the meantime, the whole collection is a click away."
    />
  );
}
