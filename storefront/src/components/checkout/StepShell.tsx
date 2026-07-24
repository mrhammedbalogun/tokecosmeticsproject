import type { ReactNode } from "react";

/** Reusable collapsible step card for the checkout flow. One StepShell per step
 * (1..5); CheckoutFlow decides `current`/`complete` from the step machine in
 * CheckoutContext. Three visual states:
 *  - current: body (children) is open, no Change button.
 *  - complete && !current: collapsed to a one-line `summary`, with a Change
 *    button that hands control back to the parent via `onChange` (typically
 *    `open(step)` from useCheckout()).
 *  - locked (neither current nor complete): just the header, de-emphasized —
 *    nothing to interact with yet.
 */
export function StepShell({
  step,
  title,
  current,
  complete,
  summary,
  onChange,
  children,
}: {
  step: number;
  title: string;
  current: boolean;
  complete: boolean;
  summary?: ReactNode;
  onChange?: () => void;
  children: ReactNode;
}) {
  const locked = !current && !complete;

  return (
    // aria-expanded on an implicit "region" role (a <section> with an accessible
    // name) is non-standard per strict ARIA 1.2, but it's the clearest signal to
    // tests/AT for "is this step's body currently open" on a disclosure widget
    // shaped like this, and is harmless in every browser/AT combo we support.
    // eslint-disable-next-line jsx-a11y/role-supports-aria-props
    <section
      aria-expanded={current}
      aria-labelledby={`checkout-step-${step}-title`}
      className={`rounded-[var(--radius-card)] bg-surface p-5 ${locked ? "opacity-50" : ""}`}
    >
      <header className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line text-sm text-muted"
            aria-hidden="true"
          >
            {complete ? "✓" : step}
          </span>
          <h2 id={`checkout-step-${step}-title`} className="font-display text-lg">
            {title}
          </h2>
        </div>
        {complete && !current && (
          <button
            type="button"
            aria-label={`Change ${title}`}
            onClick={onChange}
            className="text-sm font-medium text-accent hover:text-accent-strong"
          >
            Change
          </button>
        )}
      </header>

      {current && <div className="mt-4">{children}</div>}
      {complete && !current && <p className="mt-2 text-sm text-muted">{summary}</p>}
    </section>
  );
}
