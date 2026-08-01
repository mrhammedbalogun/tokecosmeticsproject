import type { Metadata } from "next";
import Link from "next/link";
import { requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Settings" };

/**
 * `/settings` — the index the sidebar's Settings item points at.
 *
 * It exists because the nav item already existed. Task 7 builds `/settings/audit`, and
 * without this page the link beside it would 404 — the one broken link in a shell whose
 * whole job is to prove the shell works.
 *
 * Thin on purpose: Plan-19 and Plan-20 add the rest. Listing only what is BUILT, rather
 * than greying out a menu of future pages, keeps this honest about what exists today.
 */
const SECTIONS = [
  {
    href: "/settings/payments",
    title: "Payments",
    blurb: "The bank account customers pay into, and which methods each market offers.",
  },
  {
    href: "/settings/delivery",
    title: "Delivery",
    blurb: "Delivery options, their prices and how long they take.",
  },
  {
    href: "/settings/audit",
    title: "Audit log",
    blurb: "Every write on the admin surface, and the reads that touch personal data.",
  },
];

export default async function SettingsPage() {
  await requireAdmin("/settings");

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Settings</h1>
      <p className="mt-1 text-sm text-muted">Owner-only configuration and records.</p>

      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {SECTIONS.map((section) => (
          <Link
            key={section.href}
            href={section.href}
            className="rounded-[var(--radius-card)] border border-line bg-surface p-4 transition-colors hover:border-accent"
          >
            <p className="text-sm font-semibold">{section.title}</p>
            <p className="mt-1 text-xs text-muted">{section.blurb}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
