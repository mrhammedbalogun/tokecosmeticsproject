import type { Metadata } from "next";
import { PartnerLoginForm } from "@/components/partner/PartnerLoginForm";
import { partnerLoginAction } from "./actions";

export const metadata: Metadata = {
  title: "Partner sign in",
  robots: { index: false, follow: false },
};

/** The delivery-partner portal's door (Plan-39). No gatePage(): the proxy's partner
 * branch already bounces a signed-in partner to `/partner`, and unlike the staff
 * ceremony there is no half-done state to route — this page renders for exactly
 * "no partner cookies". */
export default function PartnerLoginPage() {
  return (
    <main className="flex min-h-full items-center justify-center px-6 py-16">
      <div className="w-full max-w-sm">
        <h1 className="text-xl font-semibold tracking-tight">Toke Cosmetics — Delivery Partner</h1>
        <p className="mt-1 text-sm text-muted">
          Sign in to manage your delivery areas and prices.
        </p>
        <div className="mt-6 rounded-[var(--radius-card)] border border-line bg-surface p-6 shadow-sm">
          <PartnerLoginForm action={partnerLoginAction} />
        </div>
      </div>
    </main>
  );
}
