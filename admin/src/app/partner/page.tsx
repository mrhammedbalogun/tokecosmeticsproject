import type { Metadata } from "next";
import { PartnerRateCard } from "@/components/partner/PartnerRateCard";
import { partnerLogoutAction } from "./login/actions";

export const metadata: Metadata = {
  title: "Delivery areas & prices",
  robots: { index: false, follow: false },
};

/** The delivery-partner portal (Plan-39): one page, one job — the partner's own rate
 * card. Data flows through the partner BFF proxy from the client component, so this
 * server component stays cookie-read-free; the proxy's partner branch already
 * bounced anyone without partner cookies to the login. */
export default function PartnerHomePage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-6 py-10">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Delivery areas &amp; prices</h1>
          <p className="mt-1 text-sm text-muted">
            What you list here is exactly what Toke Cosmetics customers are offered at
            checkout — changes go live immediately.
          </p>
        </div>
        <form action={partnerLogoutAction}>
          <button
            type="submit"
            className="rounded-md border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:border-accent/60 hover:text-foreground"
          >
            Sign out
          </button>
        </form>
      </header>
      <div className="mt-8">
        <PartnerRateCard />
      </div>
    </main>
  );
}
