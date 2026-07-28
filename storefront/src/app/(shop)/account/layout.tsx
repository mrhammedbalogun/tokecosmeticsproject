import type { Metadata } from "next";
import { cookies } from "next/headers";
import type { components } from "@/lib/api-types";
import { apiFetch } from "@/lib/api";
import { ACCESS_COOKIE } from "@/lib/auth";
import { AccountNav } from "@/components/account/AccountNav";
import { SignOutButton } from "@/components/account/SignOutButton";

export const metadata: Metadata = {
  // Personal pages: nothing to index, and indexing would publish account URLs.
  robots: { index: false, follow: false },
};

type Me = components["schemas"]["Me"];

/**
 * Best-effort identity for the header chip — NEVER a gate and NEVER a bounce. The
 * layout renders in the same RSC pass as the page, and each page's own fetch carries
 * the renewal redirect with the CORRECT return path; when this layout also bounced
 * (via fetchWithAuthOrBounce with a hardcoded /account), the two redirects raced and
 * a stale-session click on "Orders" landed on the Dashboard. On any failure here the
 * shell renders anonymously; the page beneath it renews (or redirects to login), and
 * the post-bounce re-render fills the chip in.
 */
async function getOptionalMe(): Promise<Me | null> {
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) return null;
  try {
    return await apiFetch<Me>("/auth/me/", { token, cache: "no-store" });
  } catch {
    return null;
  }
}

/**
 * The account shell. Fetches `/auth/me/` once per HARD load for the header/nav —
 * this is a hint, not the gate: layouts do not re-run on soft navigation, so each
 * page's own fetch (or requireAuth) is what actually protects it (see the Plan-15
 * gating design). `cookies()` inside the fetcher makes everything under /account
 * dynamic automatically; no caching directives belong here.
 */
export default async function AccountLayout({ children }: { children: React.ReactNode }) {
  const me = await getOptionalMe();

  return (
    <section className="mx-auto max-w-5xl px-4 py-10">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="font-display text-3xl">My account</h1>
          {me && (
            <p className="mt-1 text-sm text-muted">
              {me.first_name ? `${me.first_name} · ` : ""}
              <span className="font-mono">{me.toke_id}</span>
            </p>
          )}
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
