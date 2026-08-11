"use client";
import { useEffect, useRef, useState } from "react";
import {
  fetchStreetSuggestions,
  mapsConfigured,
  resolveSuggestion,
  type PlacePick,
  type Suggestion,
} from "@/lib/googleMaps";

interface Props {
  id: string;
  value: string;
  onChangeText: (value: string) => void;
  onPick: (pick: PlacePick) => void;
  required?: boolean;
  className?: string;
}

/**
 * The street-address input with a Places assist (Plan-32b slice 3, ruling 1):
 * free text ALWAYS remains valid — the suggestions are an overlay, and every
 * failure path (no key, script blocked, API error) leaves a plain working
 * input. Mounted on the street field only, NG only (the parent gates that).
 *
 * Headless on purpose: our input, our dropdown, Google only as data — which is
 * what lets the whole thing be one mocked module in tests, keeps the styling
 * ours, and uses the session-token flow ruling 8 requires.
 */
export function AddressAutocompleteInput({
  id, value, onChangeText, onPick, required, className,
}: Props) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestQuery = useRef("");
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on outside click — the listbox must never trap the form.
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function handleChange(text: string) {
    onChangeText(text);
    if (!mapsConfigured()) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    latestQuery.current = text;
    debounceRef.current = setTimeout(async () => {
      const results = await fetchStreetSuggestions(text);
      // A slow response for an old query must not clobber the current list.
      if (latestQuery.current !== text) return;
      setSuggestions(results);
      setOpen(results.length > 0);
      setActive(-1);
    }, 250);
  }

  async function pick(s: Suggestion) {
    setOpen(false);
    setSuggestions([]);
    onChangeText(s.mainText); // immediate feedback even if details resolution fails
    const resolved = await resolveSuggestion(s.id, s.mainText);
    if (resolved) onPick(resolved);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((prev) => Math.min(prev + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((prev) => Math.max(prev - 1, 0));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault(); // don't submit the form from the listbox
      void pick(suggestions[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div ref={rootRef} className="relative">
      <input
        id={id}
        type="text"
        value={value}
        onChange={(e) => handleChange(e.target.value)}
        onKeyDown={handleKeyDown}
        required={required}
        autoComplete="address-line1"
        role="combobox"
        aria-expanded={open}
        aria-controls={`${id}-listbox`}
        aria-autocomplete="list"
        className={className}
      />
      {open && (
        <ul
          id={`${id}-listbox`}
          role="listbox"
          className="absolute z-20 mt-1 w-full rounded-[var(--radius-card)] border border-line bg-surface shadow-lg"
        >
          {suggestions.map((s, i) => (
            <li key={s.id} role="option" aria-selected={i === active}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault() /* keep input focus */}
                onClick={() => void pick(s)}
                className={`block w-full px-3 py-2 text-left text-sm ${
                  i === active ? "bg-beige" : "hover:bg-beige/60"
                }`}
              >
                <span className="font-medium">{s.mainText}</span>
                {s.secondaryText && (
                  <span className="ml-1 text-muted">{s.secondaryText}</span>
                )}
              </button>
            </li>
          ))}
          {/* Required attribution when Places results render off-map. */}
          <li aria-hidden className="border-t border-line px-3 py-1 text-right text-[10px] text-muted">
            powered by Google
          </li>
        </ul>
      )}
    </div>
  );
}
