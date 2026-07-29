"use client";

import { useEffect, useId, useRef, useState, useTransition } from "react";
import {
  MIN_QUERY_LENGTH,
  SEARCH_DEBOUNCE_MS,
  SECTION_LABELS,
  SECTION_ORDER,
  formatMoney,
  humanStatus,
  totalResults,
  type SearchResults,
  type SearchState,
} from "@/lib/search";

/**
 * The topbar search box.
 *
 * WHAT IT RENDERS ARE CARDS, NOT LINKS. Plans 17/18 build the detail pages; every result
 * here carries its useful fields inline instead, so the two questions the owner actually
 * asks — "what is the status of TC-100123" and "which customer is this email" — are
 * answered without navigating anywhere and without a single 404. See `lib/search.ts` for
 * where hrefs go when those pages exist.
 *
 * SECTIONS ARE NEVER FILTERED HERE. The response contains only the sections the caller's
 * scopes allow; this component renders what it is given. Re-deciding visibility in the
 * browser would put a second, weaker copy of the scope rule in a bundle anybody can read,
 * and the two would drift.
 *
 * THE DEBOUNCE IS UX, NOT A CONTROL. The server enforces the three-character minimum and
 * the per-user rate cap; this just avoids a request per keystroke.
 *
 * STALE RESPONSES ARE DISCARDED BY COMPARING THE TERM, not by aborting: a Server Function
 * call is not an `AbortController`-shaped thing. Two searches in flight can land out of
 * order, and showing results for "zet" under a box reading "zeta" is the kind of small
 * wrongness that makes somebody distrust the whole panel.
 */
export function GlobalSearch({
  action,
}: {
  action: (term: string) => Promise<SearchState>;
}) {
  const [term, setTerm] = useState("");
  const [state, setState] = useState<SearchState | null>(null);
  const [open, setOpen] = useState(false);
  const [isPending, startTransition] = useTransition();
  const latest = useRef("");
  const boxRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();

  useEffect(() => {
    const query = term.trim();
    latest.current = query;
    // NOTHING IS CLEARED HERE. A too-short term is handled at RENDER, by only showing a
    // `state` whose `query` still matches the box (`visible` below). Calling `setState`
    // synchronously in an effect body is a cascading render — React's own lint rule says
    // so — and deriving during render is both cheaper and the thing that makes an
    // out-of-order reply structurally unable to appear under the wrong term.
    if (query.length < MIN_QUERY_LENGTH) return;
    const timer = setTimeout(() => {
      startTransition(async () => {
        const next = await action(query);
        // Ignore anything that is no longer what the box says.
        if (latest.current === next.query) setState(next);
      });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [term, action]);

  // Close on an outside click or Escape. `mousedown` rather than `click` so the panel is
  // gone before a click elsewhere does whatever it was going to do.
  useEffect(() => {
    if (!open) return;
    function onPointer(event: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const query = term.trim();
  const showPanel = open && query.length >= MIN_QUERY_LENGTH;
  // The second half of the staleness defence, and the one that cannot be got wrong: a
  // result set is shown only while the box still says what produced it.
  const visible = state && state.query === query ? state : null;

  return (
    <div ref={boxRef} className="relative w-full max-w-md">
      <label htmlFor="global-search" className="sr-only">
        Search orders, customers and products
      </label>
      <input
        id="global-search"
        type="search"
        role="combobox"
        aria-expanded={showPanel}
        aria-controls={listboxId}
        aria-autocomplete="list"
        autoComplete="off"
        placeholder="Search orders, customers, products…"
        value={term}
        onChange={(e) => {
          setTerm(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        className="w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm outline-none placeholder:text-muted focus:border-accent"
      />

      {showPanel ? (
        <div
          id={listboxId}
          className="absolute left-0 right-0 z-20 mt-2 max-h-[70vh] overflow-y-auto rounded-[var(--radius-card)] border border-line bg-surface p-2 shadow-lg"
        >
          <SearchPanelBody state={visible} isPending={isPending} />
        </div>
      ) : null}
    </div>
  );
}

/** Split out so the panel's states can be exercised without driving the input. */
export function SearchPanelBody({
  state,
  isPending,
}: {
  state: SearchState | null;
  isPending: boolean;
}) {
  if (state?.error) {
    return (
      <p role="alert" className="px-2 py-3 text-sm text-danger">
        {state.error}
      </p>
    );
  }
  if (!state) {
    return (
      <p className="px-2 py-3 text-sm text-muted" aria-live="polite">
        {isPending ? "Searching…" : "Type to search."}
      </p>
    );
  }
  const results = state.results;
  if (totalResults(results) === 0) {
    // The same message whether the caller's role granted no sections at all or the term
    // simply matched nothing. That is not evasion — a Content editor being told "you may
    // not search orders" would learn which surfaces exist and are worth attacking, and the
    // backend answers an empty 200 for exactly the same reason.
    return (
      <p className="px-2 py-3 text-sm text-muted" aria-live="polite">
        No matches for “{state.query}”.
      </p>
    );
  }

  return (
    <div aria-live="polite">
      {SECTION_ORDER.map((key) => {
        const rows = results?.[key];
        if (!rows?.length) return null;
        return (
          <section key={key} className="mb-1 last:mb-0">
            <h2 className="px-2 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
              {SECTION_LABELS[key]}
            </h2>
            <ul>
              {rows.map((row, i) => (
                <li key={i} className="rounded px-2 py-2 hover:bg-background">
                  <ResultCard section={key} row={row} />
                </li>
              ))}
            </ul>
          </section>
        );
      })}
      <p className="px-2 pb-1 pt-2 text-[11px] text-muted">
        Showing up to 10 per section. Use the section pages for the full list.
      </p>
    </div>
  );
}

function ResultCard({ section, row }: { section: keyof SearchResults; row: unknown }) {
  if (section === "orders") {
    const order = row as NonNullable<SearchResults["orders"]>[number];
    return (
      <>
        <p className="text-sm font-medium">
          {order.number}
          {order.legacy_number ? (
            <span className="ml-2 text-xs text-muted">was {order.legacy_number}</span>
          ) : null}
        </p>
        <p className="text-xs text-muted">
          {humanStatus(order.status)} · {formatMoney(order.grand_total, order.currency)} ·{" "}
          {order.email}
        </p>
      </>
    );
  }
  if (section === "customers") {
    const customer = row as NonNullable<SearchResults["customers"]>[number];
    return (
      <>
        <p className="text-sm font-medium">
          {customer.name || customer.email}
          <span className="ml-2 text-xs text-muted">{customer.toke_id}</span>
          {!customer.is_active ? (
            <span className="ml-2 rounded bg-warn/10 px-1.5 py-0.5 text-[10px] font-semibold text-warn">
              Deletion requested
            </span>
          ) : null}
        </p>
        <p className="text-xs text-muted">{customer.email}</p>
      </>
    );
  }
  const product = row as NonNullable<SearchResults["products"]>[number];
  return (
    <>
      <p className="text-sm font-medium">{product.name}</p>
      <p className="text-xs text-muted">
        {humanStatus(product.status)}
        {product.skus.length ? ` · ${product.skus.join(", ")}` : ""}
      </p>
    </>
  );
}
