import Link from "next/link";
import type { components } from "@/lib/api-types";
import { fetchWithAuthOrBounce } from "@/lib/session";

type Me = components["schemas"]["Me"];

/**
 * Dashboard. Its own `/auth/me/` fetch IS the gate (the layout's fetch does not
 * re-run on soft navigation); Next memoizes the identical GET within one render
 * pass, so a hard load still costs one upstream call, not two.
 */
export default async function AccountPage() {
  const me = await fetchWithAuthOrBounce<Me>("/auth/me/", "/account");

  return (
    <div>
      <h2 className="font-display text-2xl">
        Hi{me.first_name ? ` ${me.first_name}` : ""} 👋
      </h2>
      <p className="mt-2 text-sm text-muted">
        Manage your details and keep your account secure.
      </p>

      {/* Given its own row above the utility tiles: this is the only card here that
          offers the customer something rather than asking them to maintain something. */}
      <Link
        href="/account/referrals"
        className="mt-6 block rounded-[var(--radius-card)] border border-accent/25 bg-accent/5 p-5 transition-colors hover:bg-accent/10"
      >
        <h3 className="font-display text-xl text-accent-strong">Refer &amp; earn</h3>
        <p className="mt-1 text-sm text-muted">
          Share your link and earn commission when friends shop. Track your earnings and
          request payouts here.
        </p>
      </Link>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Link
          href="/account/profile"
          className="rounded-[var(--radius-card)] border border-line p-4 transition-colors hover:bg-beige"
        >
          <h3 className="font-medium">Profile</h3>
          <p className="mt-1 text-sm text-muted">
            Name, phone number and marketing preferences.
          </p>
        </Link>
        <Link
          href="/account/security"
          className="rounded-[var(--radius-card)] border border-line p-4 transition-colors hover:bg-beige"
        >
          <h3 className="font-medium">Security</h3>
          <p className="mt-1 text-sm text-muted">
            Change your password or delete your account.
          </p>
        </Link>
      </div>

      <p className="mt-6 text-sm text-muted">
        Order history and saved addresses are coming to this page soon.
      </p>
    </div>
  );
}
