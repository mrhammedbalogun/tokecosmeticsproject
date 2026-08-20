"use client";

/**
 * The marketers' quoting list: every live partner rate, searchable, read-only.
 * Data arrives as props from the server component (`/partner/rates` renders
 * per-request, no-store), so "realtime" here means "as of this page load" — the
 * refresh button re-renders from the database rather than trusting anything cached.
 *
 * The search matches LGA, LCDA and the landmarks line, because a marketer is told
 * "Gbagada" or "Benson", not which LCDA row BrandnPack files it under.
 */
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { PublicRateCard, PublicRateZone } from "@/lib/partners";
import { formatNaira } from "@/lib/partners";

function matches(zone: PublicRateZone, needle: string): boolean {
  return [zone.state, zone.lga, zone.lcda_name, zone.areas_covered, zone.dispatch_zone]
    .some((field) => field.toLowerCase().includes(needle));
}

function etaLabel(zone: PublicRateZone): string {
  return zone.min_days === zone.max_days
    ? `${zone.min_days} day${zone.min_days === 1 ? "" : "s"}`
    : `${zone.min_days}–${zone.max_days} days`;
}

export function PublicRatesList({ cards }: { cards: PublicRateCard[] }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const needle = query.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      cards
        .map((card) => ({
          ...card,
          zones: needle ? card.zones.filter((z) => matches(z, needle)) : card.zones,
        }))
        .filter((card) => card.zones.length > 0),
    [cards, needle],
  );

  function refresh() {
    setRefreshing(true);
    router.refresh();
    // router.refresh() re-renders in place without a navigation event to await;
    // flip the label back after a beat so the button reads as having done something.
    window.setTimeout(() => setRefreshing(false), 800);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search state, LGA, LCDA or area — e.g. Lagos, Ikorodu, Gbagada…"
          aria-label="Search delivery areas"
          className="w-full max-w-md rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <button
          type="button"
          onClick={refresh}
          disabled={refreshing}
          className="rounded-md border border-line px-3 py-2 text-sm text-muted transition-colors hover:border-accent/60 hover:text-foreground disabled:opacity-60"
        >
          {refreshing ? "Refreshing…" : "Refresh prices"}
        </button>
      </div>

      {filtered.length === 0 && (
        <p className="text-sm text-muted">
          {needle
            ? `No delivery area matches “${query.trim()}”.`
            : "No delivery areas are live right now — please check back."}
        </p>
      )}

      {filtered.map((card) => (
        <section key={card.code}>
          <h2 className="text-sm font-semibold tracking-tight">
            {card.partner}
            <span className="ml-2 font-normal text-muted">
              {card.zones.length} area{card.zones.length === 1 ? "" : "s"}
            </span>
          </h2>
          <div className="mt-2 space-y-2">
            {groupByStateAndLga(card.zones).map(([groupName, rows]) => (
              <div key={groupName}>
                <h3 className="mt-3 text-xs font-semibold uppercase tracking-wide text-muted">
                  {groupName}
                </h3>
                <div className="mt-1 space-y-2">
                  {rows.map((zone) => (
                    <div
                      key={zone.id}
                      className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[var(--radius-card)] border border-line bg-surface px-4 py-3 text-sm"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="font-medium">{zone.lcda_name}</p>
                        <p className="mt-0.5 text-muted">{zone.areas_covered}</p>
                      </div>
                      <span className="text-muted">{etaLabel(zone)}</span>
                      <span className="w-24 text-right text-base font-semibold">
                        {formatNaira(zone.price)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/** "State · LGA" group headings, states first then LGAs, both alphabetical — a
 * marketer quoting Ibadan must not have to scan through 20 Lagos LGAs to get there. */
function groupByStateAndLga(zones: PublicRateZone[]): Array<[string, PublicRateZone[]]> {
  const byGroup = new Map<string, PublicRateZone[]>();
  for (const zone of zones) {
    const key = zone.state ? `${zone.state} · ${zone.lga}` : zone.lga;
    const list = byGroup.get(key) ?? [];
    list.push(zone);
    byGroup.set(key, list);
  }
  return [...byGroup.entries()].sort(([a], [b]) => a.localeCompare(b));
}
