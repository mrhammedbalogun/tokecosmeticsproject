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
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { Variant } from "@/lib/catalog";
import { usePdp } from "@/components/product/PdpContext";
import { formatMoney } from "@/lib/country";
import { variantLabel } from "@/lib/variant-label";
import { pickVariant, variantAxes } from "@/lib/variant-axes";

export function VariantPicker({ variants }: { variants: Variant[] }) {
  if (variants.length <= 1) return null;
  const axes = variantAxes(variants);
  if (axes.length === 0) return <NamedVariants variants={variants} />;
  return (
    <div className={`mt-5 grid gap-4 ${axes.length > 1 ? "sm:grid-cols-2" : ""}`}>
      {axes.map((axis) => (
        <AxisDropdown key={axis.name} variants={variants} axis={axis.name} values={axis.values} />
      ))}
    </div>
  );
}

/** One choice in a dropdown and the concrete variant choosing it lands on. */
interface Choice {
  key: string;
  label: string;
  target: Variant | null;
}

function AxisDropdown({ variants, axis, values }: {
  variants: Variant[]; axis: string; values: string[];
}) {
  const { variant, setVariant } = usePdp();
  const current: Record<string, string> = {};
  for (const [name, value] of Object.entries(variant?.option_values ?? {})) {
    const trimmed = String(value).trim();
    if (trimmed) current[name] = trimmed;
  }
  /* Where each value would land, holding the other axes' selections when that exact
     combination exists — so the price shown on a row is the price of clicking it. */
  const choices: Choice[] = values.map((value) => ({
    key: value,
    label: value,
    target: pickVariant(variants, current, axis, value),
  }));
  return (
    <Dropdown
      label={axis}
      choices={choices}
      selectedKey={current[axis]}
      onPick={(choice) => { if (choice.target) setVariant(choice.target); }}
    />
  );
}

/** Variants that carry no option data at all: list them by name under "Options". */
function NamedVariants({ variants }: { variants: Variant[] }) {
  const { variant, setVariant } = usePdp();
  const choices: Choice[] = variants.map((v) => ({
    key: String(v.id), label: variantLabel(v), target: v,
  }));
  return (
    <div className="mt-5">
      <Dropdown
        label="Options"
        choices={choices}
        selectedKey={variant ? String(variant.id) : undefined}
        onPick={(choice) => { if (choice.target) setVariant(choice.target); }}
      />
    </div>
  );
}

function isUnpriced(choice: Choice): boolean {
  return !choice.target || choice.target.price === null;
}

function Dropdown({ label, choices, selectedKey, onPick }: {
  label: string;
  choices: Choice[];
  selectedKey: string | undefined;
  onPick: (choice: Choice) => void;
}) {
  const id = useId();
  const labelId = `${id}-label`;
  const listId = `${id}-list`;
  const optionId = (i: number) => `${id}-opt-${i}`;

  const [open, setOpen] = useState(false);
  const selectedIndex = choices.findIndex((c) => c.key === selectedKey);
  const [active, setActive] = useState(Math.max(selectedIndex, 0));
  const rootRef = useRef<HTMLDivElement>(null);

  const openList = () => {
    setActive(Math.max(selectedIndex, 0));
    setOpen(true);
  };
  const close = () => setOpen(false);
  const choose = (i: number) => {
    const choice = choices[i];
    if (!choice || isUnpriced(choice)) return;
    onPick(choice);
    close();
  };

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
      if (!isUnpriced(choices[i])) return i;
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

  return (
    <div ref={rootRef} className="relative">
      <span id={labelId} className="block text-sm font-medium">{label}</span>
      <button
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-labelledby={labelId}
        aria-activedescendant={open ? optionId(active) : undefined}
        onClick={() => (open ? close() : openList())}
        onKeyDown={onKeyDown}
        onBlur={close}
        className={`mt-2 flex w-full items-center justify-between gap-3 rounded-lg border bg-surface
          px-3.5 py-2.5 text-left text-sm transition focus:outline-none
          focus-visible:ring-2 focus-visible:ring-accent/40
          ${open ? "border-accent" : "border-line hover:border-accent"}`}
      >
        <span className={selected ? "font-medium" : "text-muted"}>
          {selected ? selected.label : `Select ${label.toLowerCase()}`}
        </span>
        <svg
          viewBox="0 0 10 6"
          className={`h-1.5 w-2.5 shrink-0 text-muted transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        >
          <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>

      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-labelledby={labelId}
          className="variant-menu absolute left-0 top-full z-30 mt-1 max-h-72 w-full overflow-y-auto
            rounded-lg border border-line bg-surface py-1 shadow-lg"
        >
          {choices.map((choice, i) => {
            const unpriced = isUnpriced(choice);
            const isSelected = i === selectedIndex;
            const isActive = i === active;
            const target = choice.target;
            return (
              <li
                key={choice.key}
                id={optionId(i)}
                role="option"
                aria-selected={isSelected}
                aria-disabled={unpriced || undefined}
                /* mousedown would blur the trigger and close the list before click lands. */
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => { if (!unpriced) setActive(i); }}
                onClick={() => choose(i)}
                className={`flex items-center gap-3 px-3.5 py-2.5 text-sm
                  ${unpriced ? "cursor-not-allowed opacity-40" : "cursor-pointer"}
                  ${isActive && !unpriced ? "bg-beige" : ""}`}
              >
                <span className={`min-w-0 flex-1 truncate ${isSelected ? "font-medium" : ""}`}>
                  {choice.label}
                </span>
                {unpriced ? (
                  <span className="text-xs text-muted">Unavailable</span>
                ) : !target!.in_stock ? (
                  <span className="text-xs text-muted">Out of stock</span>
                ) : (
                  <span className="flex items-center gap-2">
                    {target!.low_stock && <span className="text-xs text-gold">Few left</span>}
                    <span className="tabular-nums text-muted">
                      {formatMoney(target!.price!.amount, target!.price!.currency)}
                    </span>
                  </span>
                )}
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
