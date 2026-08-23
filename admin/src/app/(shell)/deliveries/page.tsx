import type { Metadata } from "next";
import Link from "next/link";
import { getAdminMeOrNull } from "@/lib/admin-me";
import { requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Deliveries" };

/**
 * `/deliveries` — the door the sidebar's Deliveries item points at (Plan-35).
 *
 * The Settings-door pattern exactly: sections are scope-filtered (any-of, ergonomics
 * not authorization — every endpoint behind each card carries its own `HasAdminScope`).
 * Support gets the GIG table (`orders.view`, the desk's reading); a Manager also gets
 * Pickup locations (`products.manage`). The AAJ card arrived with Plan-43 — nothing is
 * ever greyed out in advance; listing only what is BUILT keeps the door honest.
 */
const SECTIONS = [
  {
    href: "/deliveries/gig",
    title: "GIG shipments",
    blurb:
      "Every GIG delivery: where it collects from, where it goes, and what it cost.",
    scopes: ["orders.view"],
  },
  {
    href: "/deliveries/aaj",
    title: "AAJ Express shipments",
    blurb:
      "Every AAJ delivery: where it collects from, where it goes, what the customer paid and what AAJ charged us.",
    scopes: ["orders.view"],
  },
  {
    href: "/deliveries/brandnpack",
    title: "BrandnPack shipments",
    blurb:
      "Every order handed to BrandnPack: zone, destination, and what it cost vs charged.",
    scopes: ["orders.view"],
  },
  {
    href: "/deliveries/pickup-locations",
    title: "Pickup locations",
    blurb: "The Toke shops carriers collect parcels from. The pin routes every order.",
    scopes: ["products.manage"],
  },
];

export default async function DeliveriesPage() {
  await requireAdmin("/deliveries");

  // Same degradation as /settings: if `admin-me` fails, no card is offered that we
  // cannot confirm the person may use.
  const held = new Set((await getAdminMeOrNull())?.scopes ?? []);
  const sections = SECTIONS.filter((s) => s.scopes.some((scope) => held.has(scope)));

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Deliveries</h1>
      <p className="mt-1 text-sm text-muted">
        Carrier shipments and the locations they collect from.
      </p>

      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {sections.map((section) => (
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
