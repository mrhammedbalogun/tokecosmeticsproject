"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { activeHref, type NavItem } from "@/lib/nav";

/**
 * The nav. Items are filtered SERVER-side by scope (see `lib/nav.visibleNav`) and passed
 * in already filtered — the browser is never handed the full list plus a rule for hiding
 * some of it, because that would put the role table in the client bundle for no benefit.
 *
 * Hiding a link is ergonomics, not authorization. Every page and every endpoint behind
 * these links checks its own scope.
 */
export function Sidebar({ items }: { items: NavItem[] }) {
  const pathname = usePathname();
  const active = activeHref(pathname ?? "/");

  return (
    <nav aria-label="Admin sections" className="flex flex-col gap-0.5 p-3">
      {items.map((item) => {
        const isActive = item.href === active;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={isActive ? "page" : undefined}
            className={[
              "rounded px-3 py-2 text-sm transition-colors",
              isActive
                ? "bg-accent text-white"
                : "text-white/70 hover:bg-shell-soft hover:text-white",
            ].join(" ")}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
