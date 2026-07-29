import { GlobalSearch } from "@/components/GlobalSearch";
import { Sidebar } from "@/components/Sidebar";
import { SignOutButton } from "@/components/SignOutButton";
import { StagingBadge } from "@/components/StagingBadge";
import { getAdminMeOrNull } from "@/lib/admin-me";
import { visibleNav } from "@/lib/nav";
import { signOutAction } from "./actions";
import { searchAction } from "./search-actions";

/**
 * The admin shell: sidebar, topbar, sign-out.
 *
 * IT DOES NOT GATE. Layouts do not re-render on every client navigation, so a check placed
 * here is a check that sometimes does not run — Plan-15's lesson, and the reason
 * `getAdminMeOrNull` answers `null` instead of redirecting. Each page inside calls
 * `requireAdmin`, and Next renders layout and page together, so a page that redirects
 * makes the whole response a redirect regardless of what this rendered.
 *
 * The consequence, stated so it does not look like a bug: if `admin-me` fails, the shell
 * renders with an empty nav. That is the correct degradation — no link is offered that we
 * cannot confirm the person may use.
 */
export default async function ShellLayout({ children }: { children: React.ReactNode }) {
  const me = await getAdminMeOrNull();
  const items = visibleNav(me?.scopes);

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-56 shrink-0 flex-col bg-shell md:flex">
        <div className="px-4 py-4">
          <p className="text-sm font-semibold tracking-tight text-white">Toke Admin</p>
          <p className="text-[11px] text-white/50">
            {me?.groups.length ? me.groups.join(", ") : "No role"}
          </p>
        </div>
        <Sidebar items={items} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-line bg-surface px-6 py-3">
          <StagingBadge />
          {/* The search box lives in the layout because it is chrome, and it is rendered
              for EVERY staff member without a scope check here. That is not an oversight:
              the endpoint returns only the sections the caller's scopes allow, so a
              Content editor gets a working box that finds nothing, and hiding it would
              mean keeping a second copy of the scope rule in the browser. */}
          <GlobalSearch action={searchAction} />
          <div className="ml-auto flex items-center gap-3">
            <span className="text-xs text-muted">{me?.email ?? "—"}</span>
            <div className="rounded bg-shell p-0.5">
              <SignOutButton action={signOutAction} />
            </div>
          </div>
        </header>
        <main className="min-w-0 flex-1 px-6 py-6">{children}</main>
      </div>
    </div>
  );
}
