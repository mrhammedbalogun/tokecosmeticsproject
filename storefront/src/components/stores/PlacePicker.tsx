"use client";

/**
 * One step of the store locator's cascade: a listbox that can be searched, driven
 * entirely from the keyboard, and read by a screen reader.
 *
 * ── WHY NOT A `<select>` ────────────────────────────────────────────────────────────
 *
 * The checkout's `RegionSelect` uses native selects and should keep doing so — it is a
 * form field in a flow whose job is to be over quickly. This is the page's centrepiece,
 * and the brief says so out loud: three default dropdowns is the thing it asks us not
 * to build. Lagos also has enough stocked LGAs to want a filter box, which a `<select>`
 * cannot offer, and the option rows here carry a second line ("3 stores") that a
 * native option cannot render.
 *
 * ── THE ACCESSIBILITY CONTRACT, STATED SO IT SURVIVES EDITS ─────────────────────────
 *
 * A collapsed picker is ONE tab stop — a button that announces its label and its
 * current value. Opening moves focus INTO the popover (the filter box when there is
 * one, the list itself when there is not) and arrow keys walk the options with
 * `aria-activedescendant`, so focus never scatters across N option elements. Escape
 * closes and returns focus to the button, which is where the reader left it. Tab
 * closes too rather than trapping — this is a menu, not a dialog.
 *
 * The filter box appears only past `SEARCH_THRESHOLD` options. Below it, a search field
 * is furniture, and on a phone it is worse than furniture: focusing it raises the
 * keyboard over the very list it is meant to help you read.
 */
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { StorePlace } from "@/lib/stores";

const SEARCH_THRESHOLD = 7;

export interface PlacePickerProps {
  /** "Country", "State", "LGA" — the country's own word for the level, where it has one. */
  label: string;
  /** The step number rendered in the marker beside the label. */
  step: number;
  options: StorePlace[];
  /** The chosen option's slug, or null. */
  value: string | null;
  onChange: (slug: string) => void;
  /** Locked until the level above it is chosen. */
  disabled?: boolean;
  loading?: boolean;
  /** What to say in the button while there is nothing to say — "Choose a state first". */
  placeholder: string;
  /** What to say when the level loaded and holds nothing. The caller overrides it when
   *  the level did NOT load — "Nothing here yet" over a failed fetch is a lie. */
  emptyText?: string;
}

export function PlacePicker({
  label,
  step,
  options,
  value,
  onChange,
  disabled = false,
  loading = false,
  placeholder,
  emptyText = "Nothing here yet",
}: PlacePickerProps) {
  const baseId = useId();
  const listboxId = `${baseId}-listbox`;
  const labelId = `${baseId}-label`;

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const selected = options.find((o) => o.slug === value) ?? null;
  const searchable = options.length > SEARCH_THRESHOLD;

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return options;
    return options.filter((o) => o.name.toLowerCase().includes(term));
  }, [options, query]);

  // OPENING IS A HANDLER, NOT AN EFFECT. Clearing the filter and homing the highlight
  // onto the current choice are consequences of the click that opened the picker, so
  // they belong in that click — `react-hooks/set-state-in-effect` is right to refuse
  // the version of this that watched `open` and set state afterwards.
  function openPicker() {
    if (disabled || loading) return;
    setQuery("");
    const index = options.findIndex((o) => o.slug === value);
    setActive(index >= 0 ? index : 0);
    setOpen(true);
  }

  // Filtering invalidates the highlight — "Ikeja" highlighted, then a keystroke that
  // filters it away, would leave Enter selecting a row nobody can see. Homing to the
  // top on every keystroke is also what makes type-then-Enter pick the obvious match.
  function onQueryChange(next: string) {
    setQuery(next);
    setActive(0);
  }

  // The one thing that IS an effect: moving focus into the popover is a DOM side
  // effect, and there is no render that can express it.
  useEffect(() => {
    if (!open) return;
    (searchable ? searchRef.current : listRef.current)?.focus();
  }, [open, searchable]);

  useEffect(() => {
    if (!open) return;
    const onDocPointer = (e: MouseEvent | TouchEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocPointer);
    document.addEventListener("touchstart", onDocPointer);
    return () => {
      document.removeEventListener("mousedown", onDocPointer);
      document.removeEventListener("touchstart", onDocPointer);
    };
  }, [open]);

  // Keep the highlighted row on screen while arrowing through a long list. Called
  // through an optional guard because jsdom does not implement `scrollIntoView` — this
  // is pure polish, and it must not be the thing that throws in a test run.
  useEffect(() => {
    if (!open) return;
    const row = listRef.current?.querySelector(`[data-index="${active}"]`);
    row?.scrollIntoView?.({ block: "nearest" });
  }, [active, open]);

  function close(refocus = true) {
    setOpen(false);
    if (refocus) buttonRef.current?.focus();
  }

  function choose(index: number) {
    const option = filtered[index];
    if (!option) return;
    onChange(option.slug);
    close();
  }

  function onPopoverKeyDown(e: React.KeyboardEvent) {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActive((a) => Math.min(a + 1, filtered.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setActive((a) => Math.max(a - 1, 0));
        break;
      case "Home":
        e.preventDefault();
        setActive(0);
        break;
      case "End":
        e.preventDefault();
        setActive(Math.max(0, filtered.length - 1));
        break;
      case "Enter":
        e.preventDefault();
        choose(active);
        break;
      case "Escape":
        e.preventDefault();
        close();
        break;
      case "Tab":
        // Close but let the browser move focus — a picker is not a dialog and must
        // not trap the tab key.
        setOpen(false);
        break;
      default:
        break;
    }
  }

  function onButtonKeyDown(e: React.KeyboardEvent) {
    if (disabled) return;
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openPicker();
    }
  }

  const buttonText = loading
    ? "Loading…"
    : selected
      ? selected.name
      : options.length === 0 && !disabled
        ? emptyText
        : placeholder;

  const activeId = filtered[active] ? `${baseId}-opt-${active}` : undefined;

  return (
    <div ref={rootRef} className="relative">
      <span
        id={labelId}
        className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.14em] text-muted"
      >
        <span
          aria-hidden
          className={`inline-flex size-5 items-center justify-center rounded-full text-[0.6875rem] font-semibold transition-colors ${
            selected
              ? "bg-accent text-surface"
              : disabled
                ? "bg-line text-muted"
                : "bg-beige text-muted ring-1 ring-line"
          }`}
        >
          {step}
        </span>
        {label}
      </span>

      <button
        ref={buttonRef}
        type="button"
        role="combobox"
        aria-controls={listboxId}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-labelledby={`${labelId} ${baseId}-value`}
        disabled={disabled || loading}
        onClick={() => (open ? close(false) : openPicker())}
        onKeyDown={onButtonKeyDown}
        className={`flex w-full items-center justify-between gap-3 rounded-[var(--radius-card)] border bg-surface px-4 py-3.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:bg-beige/60 disabled:text-muted ${
          open ? "border-accent" : selected ? "border-accent/40" : "border-line"
        } ${disabled || loading ? "" : "hover:border-accent/60"}`}
      >
        <span
          id={`${baseId}-value`}
          className={selected ? "font-medium text-foreground" : "text-muted"}
        >
          {buttonText}
        </span>
        {loading ? (
          <Spinner />
        ) : (
          <Chevron className={open ? "rotate-180" : ""} />
        )}
      </button>

      {open && (
        <div className="absolute left-0 right-0 z-40 mt-2 overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface shadow-xl">
          {searchable && (
            <div className="border-b border-line p-2">
              <input
                ref={searchRef}
                type="text"
                value={query}
                onChange={(e) => onQueryChange(e.target.value)}
                onKeyDown={onPopoverKeyDown}
                // The combobox role stays on the button so the collapsed control has
                // exactly one accessible name; this box is a plain filter field that
                // drives the same list.
                aria-label={`Filter ${label.toLowerCase()} options`}
                aria-controls={listboxId}
                aria-activedescendant={activeId}
                autoComplete="off"
                placeholder={`Search ${label.toLowerCase()}…`}
                className="w-full rounded border border-line bg-beige/60 px-3 py-2 text-sm outline-none focus:border-accent"
              />
            </div>
          )}
          <ul
            ref={listRef}
            id={listboxId}
            role="listbox"
            aria-labelledby={labelId}
            aria-activedescendant={searchable ? undefined : activeId}
            tabIndex={searchable ? -1 : 0}
            onKeyDown={searchable ? undefined : onPopoverKeyDown}
            className="max-h-64 overflow-y-auto py-1 outline-none"
          >
            {filtered.length === 0 && (
              <li className="px-4 py-3 text-sm text-muted">No matches.</li>
            )}
            {filtered.map((option, index) => (
              <li
                key={option.slug}
                id={`${baseId}-opt-${index}`}
                data-index={index}
                role="option"
                aria-selected={option.slug === value}
                onMouseEnter={() => setActive(index)}
                onClick={() => choose(index)}
                className={`flex cursor-pointer items-center justify-between gap-3 px-4 py-2.5 text-sm ${
                  index === active ? "bg-beige" : ""
                }`}
              >
                <span
                  className={option.slug === value ? "font-medium text-accent" : ""}
                >
                  {option.name}
                </span>
                <span className="shrink-0 text-xs text-muted">
                  {option.store_count} {option.store_count === 1 ? "store" : "stores"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Chevron({ className = "" }: { className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 20 20"
      className={`size-4 shrink-0 text-muted transition-transform ${className}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
    >
      <path d="M5 7.5 10 12.5 15 7.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Spinner() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 20 20"
      className="size-4 shrink-0 animate-spin text-accent"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <circle cx="10" cy="10" r="7.5" className="opacity-25" />
      <path d="M17.5 10A7.5 7.5 0 0 0 10 2.5" strokeLinecap="round" />
    </svg>
  );
}
