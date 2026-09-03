"use client";

/**
 * The pricing panel: one row per market, prefilled at the house discount, editable.
 *
 * ── THE PREFILL IS THE POINT ────────────────────────────────────────────────────────
 *
 * Every market's box opens holding `components total - N%`, computed live as items are
 * picked. Leave it and the market stays AUTOMATIC: the combo follows its components, so a
 * repricing next month carries the bundle with it and nobody has to notice. Type a
 * different number and that market becomes PINNED: the advertised price stops moving,
 * which is what an advertised price has to do.
 *
 * The distinction is stated in words on the row rather than hidden behind a toggle,
 * because "why did my ₦18,000 combo become ₦18,400" is a question nobody should have to
 * ask twice. "Follow the discount" puts a pinned row back.
 *
 * A market whose components are not all priced shows no box at all — there is no number
 * to prefill, and an empty box would read as "free".
 */
import { previewPricing, type ComboItemRow, type MarketPreview } from "@/lib/combos";
import type { CountryRef } from "@/lib/reference";

export function ComboPricingPanel({
  items,
  countries,
  markets,
  discountPercent,
  pinned,
  onDiscountPercent,
  onPin,
  onUnpin,
}: {
  items: ComboItemRow[];
  countries: CountryRef[];
  /** Market codes to show, in column order. */
  markets: string[];
  discountPercent: string;
  /** market -> the typed override. Absent = automatic. */
  pinned: Record<string, string>;
  onDiscountPercent: (value: string) => void;
  onPin: (market: string, amount: string) => void;
  onUnpin: (market: string) => void;
}) {
  const percent = Number(discountPercent) || 0;
  const rows = previewPricing(items, markets, percent, pinned);
  const symbolFor = (code: string) =>
    countries.find((c) => c.code === code)?.currency?.symbol ?? "";
  const nameFor = (code: string) => countries.find((c) => c.code === code)?.name ?? code;

  return (
    <div className="max-w-3xl">
      <div className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
        <label className="block text-xs text-muted">
          Combo discount
          <span className="mt-1 flex items-center gap-2">
            <input
              type="number"
              min={0}
              max={100}
              step="0.5"
              value={discountPercent}
              onChange={(e) => onDiscountPercent(e.target.value)}
              className="w-24 rounded border border-line bg-background px-2 py-1.5 text-right text-sm tabular-nums focus:border-accent focus:outline-none"
            />
            <span className="text-sm text-foreground">% off what the parts cost</span>
          </span>
        </label>
        <p className="mt-2 text-xs text-muted">
          This fills every market below. Change a market&rsquo;s price and that one stops
          following it.
        </p>
      </div>

      <div className="mt-4 space-y-3">
        {rows.map((row) => (
          <MarketRow
            key={row.market}
            row={row}
            name={nameFor(row.market)}
            symbol={symbolFor(row.market)}
            typed={pinned[row.market]}
            // Which products are the reason this market cannot be priced. Named here
            // rather than pointed at ("the flagged items above"), because the items panel
            // flags the HOME market only — so on a UK row that pointer led nowhere.
            unpriced={items
              .filter((i) => i.prices[row.market] == null)
              .map((i) => i.product_name)}
            onPin={onPin}
            onUnpin={onUnpin}
          />
        ))}
      </div>
    </div>
  );
}

function MarketRow({
  row,
  name,
  symbol,
  typed,
  unpriced,
  onPin,
  onUnpin,
}: {
  row: MarketPreview;
  name: string;
  symbol: string;
  typed: string | undefined;
  /** Products with no price in THIS market — the reason it cannot be sold here. */
  unpriced: string[];
  onPin: (market: string, amount: string) => void;
  onUnpin: (market: string) => void;
}) {
  const money = (value: number) =>
    `${symbol}${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  if (row.componentsTotal === null) {
    return (
      <div className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4">
        <p className="text-sm font-medium">
          {name} <span className="font-normal text-muted">({row.market})</span>
        </p>
        <p className="mt-1 text-xs text-warn">
          {unpriced.length > 0 ? (
            <>
              <strong>{unpriced.join(", ")}</strong>{" "}
              {unpriced.length === 1 ? "has" : "have"} no price in {name}, so this combo
              cannot be sold there.
            </>
          ) : (
            <>This combo cannot be priced in {name}.</>
          )}{" "}
          Price {unpriced.length === 1 ? "it" : "them"} on the product page, or untick{" "}
          {name} under <em>Where it sells</em>.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium">
            {name} <span className="font-normal text-muted">({row.market})</span>
          </p>
          <p className="mt-1 text-xs text-muted">
            Bought separately{" "}
            <span className="line-through">{money(row.componentsTotal)}</span>
          </p>
        </div>

        <label className="text-xs text-muted">
          Combo price
          <span className="mt-1 flex items-center gap-1.5">
            <span className="text-sm text-foreground">{symbol}</span>
            <input
              type="number"
              min={0}
              step="0.01"
              value={typed ?? (row.amount ?? 0).toFixed(2)}
              onChange={(e) => onPin(row.market, e.target.value)}
              className={`w-32 rounded border bg-background px-2 py-1.5 text-right text-sm tabular-nums focus:outline-none ${
                row.pinned ? "border-accent focus:border-accent" : "border-line focus:border-accent"
              }`}
            />
          </span>
        </label>

        <div className="text-right">
          <p className="text-sm font-semibold text-accent tabular-nums">
            Saves {money(row.saving ?? 0)}
          </p>
          <p className="text-xs text-muted tabular-nums">
            {(row.savingPercent ?? 0).toFixed(2).replace(/\.?0+$/, "")}% off
          </p>
        </div>
      </div>

      <p className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        {row.pinned ? (
          <>
            <span className="rounded-full bg-accent/10 px-2 py-0.5 font-medium text-accent">
              Fixed
            </span>
            <span className="text-muted">
              This price stays put when component prices change.
            </span>
            <button
              type="button"
              onClick={() => onUnpin(row.market)}
              className="underline underline-offset-2 hover:text-foreground"
            >
              Follow the discount instead
            </button>
          </>
        ) : (
          <>
            <span className="rounded-full bg-line px-2 py-0.5 font-medium text-muted">
              Automatic
            </span>
            <span className="text-muted">
              Follows the components. Type a different number to fix it.
            </span>
          </>
        )}
      </p>
    </div>
  );
}
