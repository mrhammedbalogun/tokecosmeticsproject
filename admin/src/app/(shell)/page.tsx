import type { Metadata } from "next";
import { requireAdmin } from "@/lib/session";
import { getAdminMeOrNull } from "@/lib/admin-me";
import { visibleNav } from "@/lib/nav";

export const metadata: Metadata = { title: "Dashboard" };

/**
 * The dashboard. Thin on purpose — Task 5 ships the shell and the ceremony; Plans 17-19
 * fill the panels.
 *
 * `requireAdmin("/")` is THE gate for this page. It is called here, in the page, and not
 * in the layout: see the comment in `(shell)/layout.tsx`.
 */
export default async function DashboardPage() {
  await requireAdmin("/");
  const me = await getAdminMeOrNull();
  const sections = visibleNav(me?.scopes).filter((item) => item.href !== "/");

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">
        {me?.name ? `Hello, ${me.name.split(" ")[0]}` : "Dashboard"}
      </h1>
      <p className="mt-1 text-sm text-muted">
        {me?.is_superuser
          ? "You are a superuser: every scope is granted."
          : `Role${me && me.groups.length === 1 ? "" : "s"}: ${
              me?.groups.length ? me.groups.join(", ") : "none assigned"
            }`}
      </p>

      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {sections.map((item) => (
          <a
            key={item.href}
            href={item.href}
            className="rounded-[var(--radius-card)] border border-line bg-surface p-4 transition-colors hover:border-accent"
          >
            <p className="text-sm font-semibold">{item.label}</p>
            <p className="mt-1 text-xs text-muted">Coming in a later plan.</p>
          </a>
        ))}
      </div>

      {sections.length === 0 ? (
        <p className="mt-6 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
          Your account is staff but holds no scopes. Ask the site owner to put you in a
          role group — see <code>docs/runbooks/admin-gate.md</code> §7.
        </p>
      ) : null}
    </div>
  );
}
