import type { Metadata } from "next";
import { PublicRatesList } from "@/components/partner/PublicRatesList";
import { apiFetch } from "@/lib/api";
import type { PublicRateCard } from "@/lib/partners";

export const metadata: Metadata = {
  title: "Delivery price list",
  // Public link, not a public listing: marketers get the URL from Hammed, and the
  // rest of the admin app is noindex — this page should not be the one exception.
  robots: { index: false, follow: false },
};

/** The marketers' read-only price list — Hammed's ruling (2026-08-20): a fully
 * public URL, no login, showing exactly the rates checkout offers right now.
 *
 * PUBLIC BY DESIGN, and the proxy carves it out of the partner cookie matrix — see
 * `proxy.ts`. The fetch is anonymous (no token, no BFF secret): `/partner/rates/`
 * is `AllowAny` on the backend and serves nothing checkout does not already tell
 * any guest. `apiFetch` defaults to `no-store`, and `proxy.ts` stamps no-store on
 * the rendered page, so every load re-reads the partner's live table. */
export default async function PartnerRatesPage() {
  let cards: PublicRateCard[] | null = null;
  try {
    cards = await apiFetch<PublicRateCard[]>("/partner/rates/");
  } catch {
    // Rendered below as a retry prompt — a marketer mid-sale needs a next step,
    // not a stack trace.
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-10">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">
          Toke Cosmetics — Delivery price list
        </h1>
        <p className="mt-1 text-sm text-muted">
          Live courier rates by LGA for quoting customers. Prices are exactly what
          checkout charges right now — refresh before you quote.
        </p>
      </header>
      <div className="mt-8">
        {cards === null ? (
          <p role="alert" className="rounded-[var(--radius-card)] border border-danger/30 bg-danger/5 p-4 text-sm text-danger">
            The price list could not be loaded — please refresh the page to try again.
          </p>
        ) : (
          <PublicRatesList cards={cards} />
        )}
      </div>
    </main>
  );
}
