"use client";
/**
 * The variant picker: one dropdown per option axis.
 *
 * ── WHY A DROPDOWN, AND WHY NOT <select> ────────────────────────────────────────────────
 *
 * Until 2026-08-22 single-axis products (just "Size") rendered pills and only two-axis
 * products got dropdowns (5a7937a). The shop wants every variable product to read the same
 * way, and the pills could never say what each size COSTS — the thing a shopper choosing
 * between 80g and 275g actually wants to know. A native <select> can't lay that out either
 * (no columns, no alignment, platform styling), so this is an APG "select-only combobox":
 * a button with role=combobox that owns a listbox, keyboard-driven through
 * aria-activedescendant so focus never leaves the trigger.
 *
 * Each row is a price ladder entry: `value ……… ₦price`, tabular numerals, with "Out of
 * stock" (still selectable — the buy box explains) and "Unavailable" (disabled — unpriced
 * in this region) in the price column instead of a number.
 *
 * ── NOTHING IS PRE-SELECTED (2026-09-08) ────────────────────────────────────────────────
 *
 * The trigger opens on "SELECT PRODUCT SIZE" — uppercase, so it can never be mistaken for
 * a value somebody chose. Shoppers were checking out on the first size believing it was
 * the only one. The buy buttons refuse to act until every axis is answered, and pressing
 * one focuses and reddens the axis still owed (see `promptNonce` in PdpContext).
 */
import {
  useEffect, useId, useRef, useState, type KeyboardEvent,
} from "react";
import type { Variant } from "@/lib/catalog";
import { usePdp } from "@/components/product/PdpContext";
import { formatMoney } from "@/lib/country";
import { variantLabel } from "@/lib/variant-label";
import { variantAxes, variantsMatching } from "@/lib/variant-axes";

export function VariantPicker({ variants }: { variants: Variant[] }) {
  const { selections, promptNonce } = usePdp();
  if (variants.length <= 1) return null;
  const axes = variantAxes(variants);
  if (axes.length === 0) return <NamedVariants variants={variants} />;
  // Only the FIRST unanswered axis takes focus on a prompt — the rest just redden, so a
  // two-axis product does not fight over the focus ring.
  const firstOwed = axes.find((a) => !selections[a.name])?.name;
  return (
    <div className={`mt-5 grid gap-4 ${axes.length > 1 ? "sm:grid-cols-2" : ""}`}>
      {axes.map((axis) => (
        <AxisDropdown
          key={axis.name}
          variants={variants}
          axis={axis.name}
          values={axis.values}
          prompted={promptNonce > 0 && !selections[axis.name]}
          focusSignal={promptNonce > 0 && axis.name === firstOwed ? promptNonce : null}
        />
      ))}
    </div>
  );
}

/** One row of a dropdown: a value, what picking it would cost, and what it would do. */
interface Choice {
  key: string;
  label: string;
  /** Variants this row could land on, given the OTHER axes' current answers. */
  pool: Variant[];
  /** True when no combination with this value is sold here — the row is dead. */
  disabled: boolean;
}

/** The money column for a row: one price when the pool agrees, "from ₦x" when it does
 * not (a two-axis row whose other axis is still open), a word when there is no price. */
function priceCell(choice: Choice) {
  const priced = choice.pool.filter((v) => v.price !== null);
  if (priced.length === 0) return <span className="text-xs text-muted">Unavailable</span>;
  if (!priced.some((v) => v.in_stock)) {
    return <span className="text-xs text-muted">Out of stock</span>;
  }
  const cheapest = priced.reduce((a, b) =>
    Number(a.price!.amount) <= Number(b.price!.amount) ? a : b);
  const spread = priced.some((v) => v.price!.amount !== cheapest.price!.amount);
  const lowStock = priced.length === 1 && priced[0].low_stock;
  return (
    <span className="flex items-center gap-2">
      {lowStock && <span className="text-xs text-gold">Few left</span>}
      <span className="tabular-nums text-muted">
        {spread && <span className="mr-1 text-xs">from</span>}
        {formatMoney(cheapest.price!.amount, cheapest.price!.currency)}
      </span>
    </span>
  );
}

function AxisDropdown({ variants, axis, values, prompted, focusSignal }: {
  variants: Variant[]; axis: string; values: string[];
  prompted: boolean; focusSignal: number | null;
}) {
  const { selections, select } = usePdp();
  const others: Record<string, string> = {};
  for (const [name, value] of Object.entries(selections)) {
    if (name !== axis) others[name] = value;
  }
  const choices: Choice[] = values.map((value) => {
    /* What picking this row would land on. When the other axes' answers can be kept,
       that is the row's true price; when they cannot (a hole in the matrix) the row
       falls back to every variant carrying the value, prices itself "from …", and
       picking it un-answers the axes it conflicts with. */
    const withOthers = variantsMatching(variants, { ...others, [axis]: value });
    const pool = withOthers.length
      ? withOthers
      : variantsMatching(variants, { [axis]: value });
    return {
      key: value,
      label: value,
      pool,
      disabled: !pool.some((v) => v.price !== null),
    };
  });
  return (
    <Dropdown
      label={axis}
      choices={choices}
      selectedKey={selections[axis]}
      onPick={(choice) => select(axis, choice.key)}
      prompted={prompted}
      focusSignal={focusSignal}
    />
  );
}

/** Variants that carry no option data at all: list them by name under "Options". */
function NamedVariants({ variants }: { variants: Variant[] }) {
  const { variant, setVariant, promptNonce } = usePdp();
  const choices: Choice[] = variants.map((v) => ({
    key: String(v.id), label: variantLabel(v), pool: [v],
    disabled: v.price === null,
  }));
  return (
    <div className="mt-5">
      <Dropdown
        label="Options"
        placeholder="Select an option"
        choices={choices}
        selectedKey={variant ? String(variant.id) : undefined}
        onPick={(choice) => {
          const picked = variants.find((v) => String(v.id) === choice.key);
          if (picked) setVariant(picked);
        }}
        prompted={promptNonce > 0 && !variant}
        focusSignal={promptNonce > 0 && !variant ? promptNonce : null}
      />
    </div>
  );
}

function Dropdown({ label, placeholder, choices, selectedKey, onPick, prompted, focusSignal }: {
  label: string;
  placeholder?: string;
  choices: Choice[];
  selectedKey: string | undefined;
  onPick: (choice: Choice) => void;
  prompted: boolean;
  focusSignal: number | null;
}) {
  const id = useId();
  const labelId = `${id}-label`;
  const listId = `${id}-list`;
  const errorId = `${id}-error`;
  const optionId = (i: number) => `${id}-opt-${i}`;

  const [open, setOpen] = useState(false);
  const selectedIndex = choices.findIndex((c) => c.key === selectedKey);
  const [active, setActive] = useState(Math.max(selectedIndex, 0));
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const openList = () => {
    setActive(selectedIndex >= 0 ? selectedIndex : firstEnabled(choices));
    setOpen(true);
  };
  const close = () => setOpen(false);
  const choose = (i: number) => {
    const choice = choices[i];
    if (!choice || choice.disabled) return;
    onPick(choice);
    close();
  };

  /* A buy button was pressed with this axis unanswered. FOCUS the trigger — do not
     open the list: a programmatic open is unreliable inside Android WebViews, and a
     silent failure would leave the shopper scrolled to a control that never opened.
     Focus is universal, moves the viewport by itself, and is what a required form
     field does. */
  useEffect(() => {
    if (focusSignal === null) return;
    triggerRef.current?.focus();
  }, [focusSignal]);

  /* Touch: tapping outside a focused button does not always blur it on iOS, so the
     blur-closes rule below gets a pointerdown backstop. */
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) close();
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    document.getElementById(`${id}-opt-${active}`)?.scrollIntoView?.({ block: "nearest" });
  }, [open, active, id]);

  /* Skip disabled rows when stepping, in either direction; stay put if none remain. */
  const step = (from: number, dir: 1 | -1) => {
    let i = from;
    for (let n = 0; n < choices.length; n++) {
      i = (i + dir + choices.length) % choices.length;
      if (!choices[i].disabled) return i;
    }
    return from;
  };

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (!open) openList(); else setActive((i) => step(i, 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        if (!open) openList(); else setActive((i) => step(i, -1));
        break;
      case "Home":
        if (open) { e.preventDefault(); setActive(step(-1, 1)); }
        break;
      case "End":
        if (open) { e.preventDefault(); setActive(step(0, -1)); }
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        if (open) choose(active); else openList();
        break;
      case "Escape":
        if (open) { e.preventDefault(); close(); }
        break;
      case "Tab":
        close();
        break;
    }
  };

  const selected = selectedIndex >= 0 ? choices[selectedIndex] : null;
  const invalid = prompted && !selected;

  return (
    <div ref={rootRef} className="relative">
      <span id={labelId} className="block text-sm font-medium">{label}</span>
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-labelledby={labelId}
        aria-invalid={invalid || undefined}
        aria-describedby={invalid ? errorId : undefined}
        aria-activedescendant={open ? optionId(active) : undefined}
        onClick={() => (open ? close() : openList())}
        onKeyDown={onKeyDown}
        onBlur={close}
        className={`mt-2 flex w-full items-center justify-between gap-3 rounded-lg border bg-surface
          px-3.5 py-2.5 text-left text-sm transition focus:outline-none
          focus-visible:ring-2 focus-visible:ring-accent/40
          ${invalid
            ? "border-red-600 ring-2 ring-red-600/20"
            : open ? "border-accent" : "border-line hover:border-accent"}`}
      >
        {selected ? (
          <span className="font-medium">{selected.label}</span>
        ) : (
          /* Uppercase and tracked out: a prompt, not a value. The shopper has to be
             unable to read this as "the product comes in this one". */
          <span className="font-semibold uppercase tracking-[0.06em] text-muted">
            {placeholder ?? `Select ${label}`}
          </span>
        )}
        <svg
          viewBox="0 0 10 6"
          className={`h-1.5 w-2.5 shrink-0 text-muted transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        >
          <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>

      {invalid && (
        <p id={errorId} role="alert" className="mt-1.5 text-sm text-red-700">
          {placeholder ? "Please choose an option" : `Please choose a ${label.toLowerCase()}`}
        </p>
      )}

      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-labelledby={labelId}
          className="variant-menu absolute left-0 top-full z-30 mt-1 max-h-72 w-full overflow-y-auto
            rounded-lg border border-line bg-surface py-1 shadow-lg"
        >
          {choices.map((choice, i) => {
            const isSelected = i === selectedIndex;
            const isActive = i === active;
            return (
              <li
                key={choice.key}
                id={optionId(i)}
                role="option"
                aria-selected={isSelected}
                aria-disabled={choice.disabled || undefined}
                /* mousedown would blur the trigger and close the list before click lands. */
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => { if (!choice.disabled) setActive(i); }}
                onClick={() => choose(i)}
                className={`flex items-center gap-3 px-3.5 py-2.5 text-sm
                  ${choice.disabled ? "cursor-not-allowed opacity-40" : "cursor-pointer"}
                  ${isActive && !choice.disabled ? "bg-beige" : ""}`}
              >
                <span className={`min-w-0 flex-1 truncate ${isSelected ? "font-medium" : ""}`}>
                  {choice.label}
                </span>
                {priceCell(choice)}
                <svg
                  viewBox="0 0 12 10"
                  className={`h-2.5 w-3 shrink-0 text-accent ${isSelected ? "" : "invisible"}`}
                  aria-hidden
                >
                  <path d="M1 5l3.5 3.5L11 1" fill="none" stroke="currentColor" strokeWidth="2" />
                </svg>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function firstEnabled(choices: Choice[]): number {
  const i = choices.findIndex((c) => !c.disabled);
  return i >= 0 ? i : 0;
}
