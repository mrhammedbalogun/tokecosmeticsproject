"use client";

/**
 * International phone input: flag button + searchable country/dial-code list +
 * as-you-type formatting. What the FORM submits is the hidden input — always strict
 * E.164 ("+2348023900964") or "" — so Server Actions and the backend never see the
 * display formatting. The visible input carries no `name` for the same reason.
 *
 * Validation is native-first, like every other form field in this app: an invalid
 * number sets a customValidity message on the visible input, so the browser blocks
 * submit and points at the field without any bespoke error plumbing.
 *
 * Real SVG flags (country-flag-icons) rather than emoji: Windows renders flag emoji
 * as bare letter pairs, and Windows is most of our traffic.
 */
import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AsYouType,
  getCountries,
  getCountryCallingCode,
  parsePhoneNumberFromString,
  type CountryCode,
} from "libphonenumber-js";
import * as Flags from "country-flag-icons/react/3x2";

/** The selling markets, pinned above the alphabetical list. */
const PINNED: CountryCode[] = ["NG", "GB", "US", "CA"];

const regionNames = new Intl.DisplayNames(["en"], { type: "region" });

interface Country {
  iso: CountryCode;
  name: string;
  dial: string;
}

function buildCountries(): { pinned: Country[]; rest: Country[] } {
  const all = getCountries().map((iso) => ({
    iso,
    name: regionNames.of(iso) ?? iso,
    dial: getCountryCallingCode(iso),
  }));
  all.sort((a, b) => a.name.localeCompare(b.name));
  return {
    pinned: PINNED.map((iso) => all.find((c) => c.iso === iso)).filter(
      (c): c is Country => c !== undefined,
    ),
    rest: all.filter((c) => !PINNED.includes(c.iso)),
  };
}

function Flag({ iso }: { iso: CountryCode }) {
  const Component = Flags[iso as keyof typeof Flags];
  if (!Component) return null;
  return <Component className="h-3.5 w-5 shrink-0 rounded-[2px]" aria-hidden />;
}

/** Format for display; falls back to the raw text while the number is incomplete. */
function formatDisplay(raw: string, country: CountryCode): string {
  return new AsYouType(country).input(raw);
}

export function PhoneField({
  id,
  name,
  label,
  defaultValue = "",
  defaultCountry = "NG",
  required = false,
  autoComplete = "tel",
  hint,
}: {
  id: string;
  name: string;
  label: string;
  defaultValue?: string;
  defaultCountry?: CountryCode;
  required?: boolean;
  autoComplete?: string;
  hint?: string;
}) {
  // Initial state from the stored value. Legacy rows hold national formats
  // ("08099998888"); parsing those with the default country recovers them, which is
  // exactly the soft-migration path — next save stores them clean.
  const initial = useMemo(() => {
    const parsed = parsePhoneNumberFromString(defaultValue, defaultCountry);
    if (parsed) {
      return {
        country: (parsed.country ?? defaultCountry) as CountryCode,
        text: parsed.formatInternational(),
      };
    }
    return { country: defaultCountry, text: defaultValue };
  }, [defaultValue, defaultCountry]);

  const [country, setCountry] = useState<CountryCode>(initial.country);
  const [text, setText] = useState(initial.text);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const countries = useMemo(buildCountries, []);

  // The submitted value: E.164 when the number is valid, "" otherwise.
  const parsed = parsePhoneNumberFromString(text, country);
  const e164 = parsed?.isValid() ? parsed.number : "";
  // "+234" alone (or stray punctuation) counts as empty, not as a wrong number —
  // it is what the field holds before the user has typed anything of their own.
  const isEmpty = text.replace(/[\s()+-]/g, "") === getCountryCallingCode(country) ||
    text.replace(/[\s()+-]/g, "") === "";

  // Native validation: browsers block submit on a non-empty invalid value and say why.
  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    if (!isEmpty && !e164) {
      input.setCustomValidity("Enter a valid phone number for the selected country.");
    } else {
      input.setCustomValidity("");
    }
  }, [text, country, e164, isEmpty]);

  // Close the dropdown on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    searchRef.current?.focus();
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const pickCountry = (c: Country) => {
    // Keep whatever national digits were already typed; swap the country code.
    const national = parsed?.nationalNumber ?? "";
    const nextText = national ? `+${c.dial}${national}` : `+${c.dial} `;
    setCountry(c.iso);
    setText(formatDisplay(nextText, c.iso));
    setOpen(false);
    setQuery("");
    inputRef.current?.focus();
  };

  const onChange = (value: string) => {
    // A "+" is only meaningful at the start. If one appears mid-string — a full
    // international number typed or pasted after a "+234 " left by the country
    // picker — the most recent "+" is the user's intent; drop what preceded it.
    const lastPlus = value.lastIndexOf("+");
    if (lastPlus > 0) value = value.slice(lastPlus);
    setText(formatDisplay(value, country));
    // A pasted full international number moves the flag with it.
    const ayt = new AsYouType(country);
    ayt.input(value);
    const detected = ayt.getCountry();
    if (detected && detected !== country) setCountry(detected);
  };

  // Autofill and password managers can set the value without an input event React
  // accepts; re-sync from the DOM when the user leaves the field so the hidden E.164
  // input can never disagree with what is visibly in the box.
  const onBlur = (event: React.FocusEvent<HTMLInputElement>) => {
    if (event.target.value !== text) onChange(event.target.value);
  };

  const q = query.trim().toLowerCase();
  const matches = (c: Country) =>
    !q || c.name.toLowerCase().includes(q) || c.dial.startsWith(q.replace("+", ""));
  const shown = [...countries.pinned.filter(matches), ...countries.rest.filter(matches)];

  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium">
        {label} {!required && <span className="text-muted">(optional)</span>}
      </label>
      <div ref={wrapRef} className="relative">
        <div
          className="flex w-full items-stretch rounded-[var(--radius-card)] border border-line bg-beige
            focus-within:ring-2 focus-within:ring-accent/40"
        >
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-label={`Country: ${regionNames.of(country) ?? country} (+${getCountryCallingCode(country)})`}
            aria-expanded={open}
            aria-haspopup="listbox"
            className="flex items-center gap-1.5 rounded-l-[var(--radius-card)] border-r border-line px-3
              hover:bg-line/40 focus:outline-none"
          >
            <Flag iso={country} />
            <svg viewBox="0 0 10 6" className="h-1.5 w-2.5 text-muted" aria-hidden>
              <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
            </svg>
          </button>
          <input
            ref={inputRef}
            id={id}
            type="tel"
            value={text}
            onChange={(e) => onChange(e.target.value)}
            onBlur={onBlur}
            required={required}
            autoComplete={autoComplete}
            inputMode="tel"
            placeholder={`+${getCountryCallingCode(country)}`}
            className="w-full rounded-r-[var(--radius-card)] bg-transparent px-3 py-2 text-sm focus:outline-none"
          />
        </div>

        {/* What actually submits: clean E.164 or empty. */}
        <input type="hidden" name={name} value={e164} />

        {open && (
          <div
            className="absolute left-0 top-full z-20 mt-1 w-full min-w-64 rounded-[var(--radius-card)]
              border border-line bg-surface shadow-lg"
          >
            <div className="border-b border-line p-2">
              <input
                ref={searchRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search for countries"
                aria-label="Search for countries"
                className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-1.5 text-sm
                  focus:outline-none focus:ring-2 focus:ring-accent/40"
              />
            </div>
            <ul role="listbox" aria-label="Country" className="max-h-60 overflow-y-auto py-1">
              {shown.map((c) => (
                <li key={c.iso}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={c.iso === country}
                    onClick={() => pickCountry(c)}
                    className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm hover:bg-beige ${
                      c.iso === country ? "bg-beige" : ""
                    }`}
                  >
                    <Flag iso={c.iso} />
                    <span className="truncate">
                      {c.name} <span className="text-muted">(+{c.dial})</span>
                    </span>
                    {c.iso === country && (
                      <svg viewBox="0 0 12 10" className="ml-auto h-2.5 w-3 shrink-0 text-accent" aria-hidden>
                        <path d="M1 5l3.5 3.5L11 1" fill="none" stroke="currentColor" strokeWidth="2" />
                      </svg>
                    )}
                  </button>
                </li>
              ))}
              {shown.length === 0 && (
                <li className="px-3 py-2 text-sm text-muted">No countries match.</li>
              )}
            </ul>
          </div>
        )}
      </div>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}
