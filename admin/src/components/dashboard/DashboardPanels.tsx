/**
 * The dashboard's panels (Plan-20b). Presentational — the page fetches.
 *
 * ── ONE CHART, NO DONUT, NO CHART LIBRARY ───────────────────────────────────────────
 *
 * The spec asked for an orders-by-status donut. It is decoration for a store doing a
 * handful of orders a day, a count strip says more in less space, and a pie invites the
 * modelling mistake `orders/models.py` warns about — needs-review is a FLAG, not a status,
 * so it can never be a slice.
 *
 * That leaves one revenue series per currency, drawn as plain SVG bars. Plan-20 ruling 3:
 * take `recharts` the moment this needs tooltips or multi-series axes, and do not
 * hand-roll a charting library to avoid a dependency. One rectangle per day is not that.
 */
import Link from "next/link";
import {
  ORDERS_NEEDING_ATTENTION,
  buildBars,
  deltaTone,
  formatDelta,
  orderStatuses,
  pairByCurrency,
  percentDelta,
  type DayRow,
  type RevenueRow,
  type StatusRow,
} from "@/lib/dashboard";

const TONE: Record<string, string> = {
  up: "text-ok",
  down: "text-warn",
  flat: "text-muted",
};

function money(value: string | undefined, currency: string): string {
  if (value === undefined) return "—";
  const n = Number(value);
  return `${currency} ${Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value}`;
}

export function KpiCards({
  current,
  previous,
}: {
  current: RevenueRow[];
  previous: RevenueRow[];
}) {
  const pairs = pairByCurrency(current, previous);
  if (!pairs.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
        No orders in this range.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {pairs.map(({ currency, current: now, previous: before }) => {
        const metrics = [
          {
            label: "Net revenue",
            value: money(now?.net, currency),
            delta: percentDelta(Number(now?.net ?? 0), Number(before?.net ?? 0)),
            higherIsBetter: true,
          },
          {
            label: "Orders",
            value: String(now?.orders ?? 0),
            delta: percentDelta(now?.orders ?? 0, before?.orders ?? 0),
            higherIsBetter: true,
          },
          {
            label: "Average order",
            value: money(now?.aov, currency),
            delta: percentDelta(Number(now?.aov ?? 0), Number(before?.aov ?? 0)),
            higherIsBetter: true,
          },
          {
            label: "Refunds",
            value: money(now?.refunds, currency),
            delta: percentDelta(Number(now?.refunds ?? 0), Number(before?.refunds ?? 0)),
            // More refunds is not good news, so the arrow reads the other way.
            higherIsBetter: false,
          },
        ];
        return (
          <section key={currency}>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
              {currency}
            </h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {metrics.map((m) => (
                <div
                  key={m.label}
                  className="rounded-[var(--radius-card)] border border-line p-4"
                >
                  <p className="text-xs text-muted">{m.label}</p>
                  <p className="mt-1 text-lg font-semibold tabular-nums">{m.value}</p>
                  <p className={`mt-1 text-xs ${TONE[deltaTone(m.delta, m.higherIsBetter)]}`}>
                    {formatDelta(m.delta)} vs previous
                  </p>
                </div>
              ))}
            </div>
          </section>
        );
      })}
      <p className="text-xs text-muted">
        Totals are per currency and never added together. &ldquo;—&rdquo; means the
        previous period had nothing to compare against.
      </p>
    </div>
  );
}

export function RevenueChart({
  rows,
  start,
  end,
}: {
  rows: DayRow[];
  start: string;
  end: string;
}) {
  const currencies = [...new Set(rows.map((r) => r.currency_id))].sort();
  if (!currencies.length) return null;

  return (
    <div className="space-y-4">
      {currencies.map((currency) => {
        const bars = buildBars(
          rows.filter((r) => r.currency_id === currency),
          start,
          end,
        );
        const peak = Math.max(...bars.map((b) => b.value), 0);
        return (
          <section key={currency} className="rounded-[var(--radius-card)] border border-line p-4">
            <div className="flex items-baseline justify-between">
              <h2 className="text-sm font-semibold">Revenue · {currency}</h2>
              <span className="text-xs text-muted">
                peak {peak.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </span>
            </div>
            <div
              className="mt-3 flex h-32 items-end gap-[2px]"
              role="img"
              aria-label={`Daily ${currency} revenue from ${start} to ${end}`}
            >
              {bars.map((bar) => (
                <div
                  key={bar.day}
                  // A zero day still gets a hairline, so the axis reads as a timeline
                  // rather than as missing data.
                  style={{ height: `${Math.max(bar.height * 100, 1)}%` }}
                  className={`flex-1 rounded-sm ${bar.value > 0 ? "bg-accent" : "bg-line"}`}
                  title={`${bar.day}: ${bar.value.toLocaleString()}`}
                />
              ))}
            </div>
            <p className="mt-2 flex justify-between text-xs text-muted">
              <span>{start}</span>
              <span>{end}</span>
            </p>
          </section>
        );
      })}
    </div>
  );
}

export function StatusStrip({ rows }: { rows: StatusRow[] }) {
  const ordered = orderStatuses(rows);
  if (!ordered.length) return null;

  return (
    <section className="rounded-[var(--radius-card)] border border-line p-4">
      <h2 className="text-sm font-semibold">Orders by status</h2>
      <ul className="mt-3 flex flex-wrap gap-2">
        {ordered.map((row) => (
          <li key={row.status}>
            <Link
              href={`/orders?status=${row.status}`}
              className="inline-flex items-center gap-2 rounded-full border border-line px-3 py-1 text-sm hover:border-accent"
            >
              <span className="text-muted">{row.status.replace(/_/g, " ")}</span>
              <span className="tabular-nums font-medium">{row.orders}</span>
            </Link>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">
        Every status, including orders that never paid. Orders needing a decision are
        flagged, not a status — see the queue below.
      </p>
    </section>
  );
}

export function AttentionWidgets({
  needsReview,
  lowStock,
  expiring,
}: {
  needsReview: number | null;
  lowStock: number | null;
  expiring: number | null;
}) {
  // COUNTS AND LINKS, NEVER RE-DERIVED. Low stock is already defined identically in the
  // digest and the inventory grid; needs-review belongs to the 18a order desk. These
  // numbers come from those endpoints so a third definition cannot drift from them.
  const cards = [
    {
      label: "Orders needing a decision",
      count: needsReview,
      href: `/orders?${ORDERS_NEEDING_ATTENTION}`,
      blurb: "Money that did not add up — each one is a refund decision.",
      warn: (needsReview ?? 0) > 0,
    },
    {
      label: "Low stock",
      count: lowStock,
      href: "/inventory?low_stock=1",
      blurb: "At or below their own threshold.",
      warn: (lowStock ?? 0) > 0,
    },
    {
      label: "Awaiting payment",
      count: expiring,
      href: "/orders?status=pending_payment",
      blurb: "Bank transfers on a 24-hour hold. These expire if nobody pays.",
      warn: false,
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {cards.map((card) => (
        <Link
          key={card.label}
          href={card.href}
          className={`rounded-[var(--radius-card)] border p-4 transition-colors hover:border-accent ${
            card.warn ? "border-warn/40 bg-warn/5" : "border-line"
          }`}
        >
          <p className="text-xs text-muted">{card.label}</p>
          <p
            className={`mt-1 text-lg font-semibold tabular-nums ${card.warn ? "text-warn" : ""}`}
          >
            {card.count === null ? "—" : card.count}
          </p>
          <p className="mt-1 text-xs text-muted">{card.blurb}</p>
        </Link>
      ))}
    </div>
  );
}
