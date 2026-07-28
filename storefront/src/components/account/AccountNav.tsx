"use client";

/**
 * Side nav (desktop) / scrollable tabs (mobile) for the account area. Lists ONLY
 * pages that exist — orders arrived with 15c, addresses with this task; wishlist is
 * the next 15d task, and a visible link to a 404 is worse than no link.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/account", label: "Dashboard" },
  { href: "/account/orders", label: "Orders" },
  { href: "/account/addresses", label: "Addresses" },
  { href: "/account/profile", label: "Profile" },
  { href: "/account/security", label: "Security" },
] as const;

/** Nested routes light up their section: /account/orders/TC-100038 keeps "Orders"
 * highlighted. Dashboard is exact-match only — "/account" prefixes every other route,
 * so a prefix rule there would light up two tabs on every page. */
function isActive(pathname: string, href: string): boolean {
  if (href === "/account") return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AccountNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Account" className="md:w-44 md:shrink-0">
      <ul className="flex gap-2 overflow-x-auto md:flex-col md:gap-1">
        {LINKS.map(({ href, label }) => {
          const active = isActive(pathname, href);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={
                  "block whitespace-nowrap rounded-[var(--radius-card)] px-3 py-2 text-sm transition-colors " +
                  (active
                    ? "bg-accent/10 font-medium text-accent-strong"
                    : "text-muted hover:bg-beige hover:text-foreground")
                }
              >
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
