import type { Metadata } from "next";
import { PagePlaceholder } from "@/components/content/PagePlaceholder";
import { pageMetadata } from "@/lib/seo";

/** `/skin-quiz` — a top-level header nav item.
 *
 * Placeholder so the approved nav never 404s; the real Skin Quiz is on the roadmap.
 * Converted to the shared `PagePlaceholder` (2026-08-16); see that component for why. */
export const metadata: Metadata = pageMetadata({
  // BARE title — the root layout appends " | Toke Cosmetics". This page used to declare
  // "Skin Quiz — Toke Cosmetics" and therefore rendered the brand twice.
  title: "Skin Quiz",
  description:
    "Answer a few questions and we will match you to a Toke Cosmetics routine for your skin.",
  path: "/skin-quiz",
});

export default function Page() {
  return (
    <PagePlaceholder
      title="Skin Quiz"
      intro="Answer a few questions and we will match you to a routine built for your skin. We are putting the finishing touches on this — in the meantime, the whole collection is a click away."
    />
  );
}
