import type { Metadata } from "next";
import type { components } from "@/lib/api-types";
import { fetchWithAuthOrBounce } from "@/lib/session";
import { AccountNav } from "@/components/account/AccountNav";
import { SignOutButton } from "@/components/account/SignOutButton";

export const metadata: Metadata = {
  // Personal pages: nothing to index, and indexing would publish account URLs.
  robots: { index: false, follow: false },
};

type Me = components["schemas"]["Me"];

/**
 * The account shell. Fetches `/auth/me/` once per HARD load for the header/nav —
 * this is a hint, not the gate: layouts do not re-run on soft navigation, so each
 * page's own fetch (or requireAuth) is what actually protects it (see the Plan-15
 * gating design). `cookies()` inside the fetcher makes everything under /account
 * dynamic automatically; no caching directives belong here.
 */
export default async function AccountLayout({ children }: { children: React.ReactNode }) {
  const me = await fetchWithAuthOrBounce<Me>("/auth/me/", "/account");

  return (
    <section className="mx-auto max-w-5xl px-4 py-10">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="font-display text-3xl">My account</h1>
          <p className="mt-1 text-sm text-muted">
            {me.first_name ? `${me.first_name} · ` : ""}
            <span className="font-mono">{me.toke_id}</span>
          </p>
        </div>
        <SignOutButton />
      </header>

      <div className="mt-8 flex flex-col gap-8 md:flex-row">
        <AccountNav />
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </section>
  );
}
