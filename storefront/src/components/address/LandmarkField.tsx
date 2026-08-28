"use client";

/**
 * "Landmark" — the nearby thing that actually gets a rider to the door.
 *
 * WHY IT EXISTS. A Nigerian street address frequently is not enough to find a house:
 * numbering is inconsistent, streets repeat across areas, and riders navigate by
 * well-known places. "Opposite Shoprite, off Ikeja bus stop" is what closes the last
 * hundred metres. Required in NG and rendered nowhere else — a GB/US/CA parcel routes on
 * its postcode, and asking a London shopper for their nearest bus stop reads as a broken
 * form. The requirement itself is enforced server-side by
 * `apps.core.address_rules.required_fields_for`; this component only decides what the
 * shopper sees, exactly as address-fields.ts describes for every other per-country field.
 *
 * ONE COMPONENT, TWO FORMS. Rendered by both `checkout/AddressStep` and
 * `account/AddressForm`. They already duplicate a lot of markup, and this is the field
 * most likely to drift, because most of it is the EXPLANATION rather than the input:
 * shoppers do not reliably know what "landmark" is being asked for, and two forms giving
 * two different answers is how a required field turns into an abandoned checkout.
 *
 * THE HELP POPUP is a real popover, not a `title=` tooltip: `title` never appears on
 * touch, and the majority of this shop's traffic is phones. It is keyboard-reachable,
 * closes on Escape and on outside click, and is labelled so a screen reader announces the
 * button as "What is a landmark?" rather than "question mark".
 */
import { useEffect, useId, useRef, useState } from "react";

export const LANDMARK_MAX = 120; // mirrors Address.landmark's max_length

/** Examples, in the shopper's own vocabulary. Deliberately concrete — an abstract
 *  definition ("a recognisable feature") is what produces "my house" as an answer. */
const EXAMPLES = [
  "A popular bus stop — “off Ikeja bus stop”",
  "A shopping mall or market — “opposite Ikeja City Mall”",
  "A filling station, bank or church nearby",
  "A well-known junction or roundabout",
];

export function LandmarkField({
  value,
  onChange,
  errors,
  /** Distinguishes the two forms' inputs. Both can exist in one document (the account
   *  page can render its form while a checkout draft is mounted), and a duplicate id
   *  would point one form's <label> at the other form's input. */
  idPrefix,
}: {
  value: string;
  onChange: (value: string) => void;
  errors?: string[];
  idPrefix: string;
}) {
  const [open, setOpen] = useState(false);
  const inputId = `${idPrefix}-landmark`;
  const helpId = useId();
  const wrapRef = useRef<HTMLDivElement>(null);

  // Escape and outside-click both close it. A popover that can only be dismissed by
  // finding the same small button again is worse than no popover on a phone.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  return (
    <div ref={wrapRef} className="relative">
      <div className="mb-1 flex items-center gap-1.5">
        <label htmlFor={inputId} className="block text-sm font-medium">
          Landmark
        </label>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={open ? helpId : undefined}
          aria-label="What is a landmark?"
          className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-muted text-[10px] font-semibold leading-none text-muted transition-colors hover:border-accent hover:text-accent"
        >
          ?
        </button>
      </div>

      {open && (
        <div
          id={helpId}
          role="dialog"
          aria-label="What is a landmark?"
          className="absolute left-0 top-7 z-20 w-full max-w-sm rounded-[var(--radius-card)] border border-line bg-surface p-4 text-sm shadow-lg"
        >
          <p className="font-medium">What is a landmark?</p>
          <p className="mt-1 text-muted">
            A well-known place near your address, so our rider can find you quickly.
          </p>
          <ul className="mt-2 space-y-1 text-muted">
            {EXAMPLES.map((e) => (
              <li key={e} className="flex gap-2">
                <span aria-hidden>•</span>
                <span>{e}</span>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="mt-3 text-sm text-accent underline underline-offset-2"
          >
            Got it
          </button>
        </div>
      )}

      <input
        id={inputId}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
        maxLength={LANDMARK_MAX}
        placeholder="e.g. Opposite Ikeja City Mall"
        // Not an autocomplete token: the browser's address vocabulary has no landmark,
        // and guessing one ("address-line3") would autofill it with something wrong.
        autoComplete="off"
        aria-describedby={`${inputId}-hint`}
        className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
      />
      <p id={`${inputId}-hint`} className="mt-1 text-xs text-muted">
        A nearby bus stop, mall or junction — it helps our rider find you.
      </p>
      {errors && (
        <p role="alert" className="mt-1 text-sm text-red-700">
          {errors.join(" ")}
        </p>
      )}
    </div>
  );
}
