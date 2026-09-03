"use client";

/**
 * The builder's product box: type, see suggestions with pictures, pick a variant.
 *
 * ── WHY PICKING IS TWO STEPS AND NOT ONE ────────────────────────────────────────────
 *
 * A suggestion is a PRODUCT; what goes in a box is a VARIANT. For a single-variant
 * product those are the same thing and the row adds straight away — asking "which 250ml?"
 * when there is only one is friction for its own sake. For a product with options, the
 * row expands in place into its variants, each with its own price, so the choice is made
 * against the same list the shop sells from rather than from memory.
 *
 * ── STALE RESPONSES ARE DISCARDED BY COMPARING THE TERM ─────────────────────────────
 *
 * Same rule as `GlobalSearch`, and for the same reason: two searches in flight can land
 * out of order, and showing results for "she" under a box reading "shea" is the kind of
 * small wrongness that makes somebody distrust the whole panel. A Server Function call is
 * not an `AbortController`-shaped thing, so the guard is the term, not an abort.
 *
 * THE DEBOUNCE IS UX, NOT A CONTROL. The endpoint enforces its own two-character minimum.
 */
import { useEffect, useId, useRef, useState, useTransition } from "react";
import { optionSummary, type PickerProduct, type PickerVariant } from "@/lib/combos";

const DEBOUNCE_MS = 220;
const MIN_QUERY = 2;

export interface PickedVariant {
  variant: PickerVariant;
  product: PickerProduct;
}

export function ProductPicker({
  search,
  onPick,
  alreadyPicked,
  market,
  currencySymbol,
}: {
  search: (term: string) => Promise<PickerProduct[]>;
  onPick: (picked: PickedVariant) => void;
  /** Variant ids already in the combo — shown as "added" rather than hidden, so a
   *  curator searching for something they added five rows ago is told, not puzzled. */
  alreadyPicked: readonly number[];
  /** Which market's price to show beside a variant. The builder's home market. */
  market: string;
  currencySymbol: string;
}) {
  const [term, setTerm] = useState("");
  const [results, setResults] = useState<PickerProduct[]>([]);
  const [shownFor, setShownFor] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [isPending, startTransition] = useTransition();
  const latest = useRef("");
  const listId = useId();

  useEffect(() => {
    const query = term.trim();
    latest.current = query;
    if (query.length < MIN_QUERY) return;
    const timer = setTimeout(() => {
      startTransition(async () => {
        const hits = await search(query);
        // Derived at render from `shownFor`, so an out-of-order reply cannot appear
        // under the wrong term even if this check were ever removed.
        if (latest.current !== query) return;
        setResults(hits);
        setShownFor(query);
        setExpanded(hits.length === 1 ? hits[0].id : null);
      });
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [term, search]);

  const query = term.trim();
  const visible = query.length >= MIN_QUERY && shownFor === query;

  const pick = (product: PickerProduct, variant: PickerVariant) => {
    onPick({ product, variant });
    setTerm("");
    setResults([]);
    setShownFor("");
    setExpanded(null);
  };

  return (
    <div className="relative">
      <label className="block text-xs text-muted" htmlFor={`${listId}-input`}>
        Add a product
      </label>
      <div className="relative mt-1">
        <svg
          viewBox="0 0 20 20" aria-hidden="true"
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
        >
          <path
            d="M9 3a6 6 0 104.2 10.3l3.5 3.5 1.4-1.4-3.5-3.5A6 6 0 009 3zm0 2a4 4 0 110 8 4 4 0 010-8z"
            fill="currentColor"
          />
        </svg>
        <input
          id={`${listId}-input`}
          type="search"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="Search products by name…"
          autoComplete="off"
          role="combobox"
          aria-expanded={visible}
          aria-controls={listId}
          className="w-full rounded-lg border border-line bg-surface py-2 pl-9 pr-3 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none"
        />
        {isPending && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted">
            searching…
          </span>
        )}
      </div>

      {query.length > 0 && query.length < MIN_QUERY && (
        <p className="mt-1 text-xs text-muted">Keep typing — two letters or more.</p>
      )}

      {visible && (
        <div
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 max-h-96 w-full overflow-auto rounded-lg border border-line bg-surface shadow-lg"
        >
          {results.length === 0 && (
            <p className="px-3 py-4 text-sm text-muted">
              Nothing matches “{query}”.
            </p>
          )}
          {results.map((product) => {
            const open = expanded === product.id;
            const single = product.variants.length === 1;
            return (
              <div key={product.id} className="border-b border-line last:border-0">
                <button
                  type="button"
                  onClick={() =>
                    single
                      ? pick(product, product.variants[0])
                      : setExpanded(open ? null : product.id)
                  }
                  disabled={product.variants.length === 0}
                  className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-accent/5 disabled:opacity-50"
                >
                  <Thumb src={product.image} alt="" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{product.name}</span>
                    <span className="block text-xs text-muted">
                      {product.variants.length === 0
                        ? "No active variants"
                        : single
                          ? formatPrice(product.variants[0].prices[market], currencySymbol)
                          : `${product.variants.length} options`}
                    </span>
                  </span>
                  {!single && product.variants.length > 0 && (
                    <span aria-hidden="true" className="text-muted">
                      {open ? "▾" : "▸"}
                    </span>
                  )}
                </button>

                {open && !single && (
                  <ul className="border-t border-line bg-background/60">
                    {product.variants.map((variant) => {
                      const added = alreadyPicked.includes(variant.id);
                      return (
                        <li key={variant.id}>
                          <button
                            type="button"
                            role="option"
                            aria-selected={added}
                            disabled={added}
                            onClick={() => pick(product, variant)}
                            className="flex w-full items-center gap-3 py-2 pl-12 pr-3 text-left text-sm hover:bg-accent/10 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <span className="min-w-0 flex-1 truncate">
                              {optionSummary(variant.option_values, variant.name)}
                              <span className="ml-2 font-mono text-[11px] text-muted">
                                {variant.sku}
                              </span>
                            </span>
                            <span className="shrink-0 text-xs tabular-nums text-muted">
                              {added ? "added" : formatPrice(variant.prices[market], currencySymbol)}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function formatPrice(amount: string | null | undefined, symbol: string): string {
  if (amount == null) return "no price";
  return `${symbol}${Number(amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

export function Thumb({ src, alt, size = 36 }: { src: string | null; alt: string; size?: number }) {
  if (!src) {
    return (
      <span
        aria-hidden="true"
        style={{ width: size, height: size }}
        className="shrink-0 rounded bg-line"
      />
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- media comes from the API's CDN
    <img
      src={src}
      alt={alt}
      width={size}
      height={size}
      style={{ width: size, height: size }}
      className="shrink-0 rounded object-cover"
    />
  );
}
