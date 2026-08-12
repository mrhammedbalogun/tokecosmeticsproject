"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { welcomeFor, isGeoSuggestionDismissed, dismissGeoSuggestion } from "@/lib/geo";
import { OverlayPortal } from "@/components/layout/OverlayPortal";

// MUST stay in sync with the backend's active markets (GET /meta/countries/) and the
// mirrored list in proxy.ts. Hardcoded on purpose to keep the first-visit popup
// dependency-free — no markets fetch on the critical path of every page.
const MARKETS = [
  { code: "NG", place: "Nigeria", currency: "NGN", symbol: "₦", currencyName: "Nigerian Naira" },
  { code: "GB", place: "the United Kingdom", currency: "GBP", symbol: "£", currencyName: "British Pounds" },
  { code: "US", place: "the United States", currency: "USD", symbol: "$", currencyName: "US Dollars" },
  { code: "CA", place: "Canada", currency: "CAD", symbol: "CA$", currencyName: "Canadian Dollars" },
  { code: "ZZ", place: "abroad", currency: "USD", symbol: "$", currencyName: "US Dollars" },
];
const MARKET_CODES = MARKETS.map((m) => m.code);

function market(code: string) {
  return MARKETS.find((m) => m.code === code) ?? MARKETS[0];
}

/**
 * First-visit currency popup. The proxy already seeded the visitor's market from geo, so
 * the default variant only CONFIRMS ("we've set prices to CAD") with a way out; the
 * "offer" variant (cookie disagrees with geo — pre-geo-seeding visitors) asks first.
 * Shows once per browser (localStorage flag shared with CountrySwitcher), never during
 * checkout, and only after a short delay so the page lands before the greeting.
 */
export function CurrencyWelcomeModal({
  currentCountry,
  geoCountry,
}: {
  currentCountry: string;
  geoCountry: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const [pending, start] = useTransition();
  const dialogRef = useRef<HTMLDivElement>(null);
  const primaryRef = useRef<HTMLButtonElement>(null);

  const welcome = welcomeFor(currentCountry, geoCountry, MARKET_CODES);

  // Reveal gate: localStorage is client-only, so SSR and the hydration render output
  // nothing; only after mount (plus a beat for the page to settle) may the popup appear.
  // Never during checkout — a currency prompt mid-purchase is a great way to lose one.
  useEffect(() => {
    if (!welcome || pathname.startsWith("/checkout") || isGeoSuggestionDismissed()) return;
    const t = setTimeout(() => setOpen(true), 700);
    return () => clearTimeout(t);
    // Mount-only by design: props are request-scoped and the flag never un-dismisses.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Focus the primary action when the dialog appears, and keep Tab inside it (the page
  // behind is inert to pointers but not to the keyboard without this).
  useEffect(() => {
    if (!open) return;
    primaryRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") return close();
      if (e.key !== "Tab" || !dialogRef.current) return;
      const focusables = dialogRef.current.querySelectorAll<HTMLElement>(
        "button, a[href], [tabindex]:not([tabindex='-1'])",
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, choosing]);

  if (!open || !welcome) return null;

  const geo = market(welcome.market);
  const current = market(currentCountry);

  /** Any exit — OK, ✕, Escape, backdrop — resolves the greeting for good. */
  function close() {
    dismissGeoSuggestion();
    setOpen(false);
  }

  /** Switch to a market: same cookie write CountrySwitcher uses, then re-render prices. */
  function switchTo(code: string) {
    if (code === currentCountry) return close();
    start(async () => {
      const res = await fetch("/api/country", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code }),
      });
      if (!res.ok) return; // leave the dialog up; the visitor can retry or dismiss
      dismissGeoSuggestion();
      setOpen(false);
      router.refresh();
    });
  }

  return (
    <OverlayPortal>
      <div className="welcome-backdrop fixed inset-0 z-50 flex items-end justify-center bg-black/30 sm:items-center sm:p-6">
        <button
          aria-label="Close"
          tabIndex={-1}
          onClick={close}
          className="absolute inset-0 cursor-default"
        />
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="currency-welcome-title"
          className="welcome-card relative w-full rounded-t-2xl bg-surface px-6 pb-8 pt-10 text-center shadow-2xl sm:max-w-md sm:rounded-2xl sm:px-10"
        >
          <button
            onClick={close}
            aria-label="Close"
            className="absolute right-4 top-4 text-muted transition-colors hover:text-foreground"
          >
            ✕
          </button>

          {/* Signature: currency medallion — an embossed-seal nod to a cosmetic jar lid. */}
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full border border-gold/50 bg-beige outline outline-1 outline-offset-4 outline-line">
            <span className="font-display text-lg text-accent-strong">{geo.symbol}</span>
          </div>

          <p className="mt-5 text-[0.7rem] font-medium uppercase tracking-[0.22em] text-muted">
            Welcome to Toke Cosmetics
          </p>

          {choosing ? (
            <>
              <h2 id="currency-welcome-title" className="mt-2 font-display text-2xl">
                Choose your country
              </h2>
              <ul className="mt-6 divide-y divide-line overflow-hidden rounded-xl border border-line text-left">
                {MARKETS.map((m) => (
                  <li key={m.code}>
                    <button
                      onClick={() => switchTo(m.code)}
                      disabled={pending}
                      className="flex w-full items-baseline justify-between gap-3 px-4 py-3 transition-colors hover:bg-beige/60 disabled:opacity-60"
                    >
                      <span className="font-medium">
                        {m.code === "ZZ" ? "International" : m.place.replace(/^the /, "")}
                      </span>
                      <span className="text-sm text-muted">
                        {m.currency} · {m.symbol}
                        {m.code === currentCountry && (
                          <span className="ml-2 text-accent" aria-label="Current selection">✓</span>
                        )}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : welcome.kind === "confirm" ? (
            <>
              <h2 id="currency-welcome-title" className="mt-2 text-balance font-display text-2xl leading-snug">
                You&apos;re shopping in {geo.currencyName}
              </h2>
              <p className="mx-auto mt-3 max-w-xs text-sm leading-relaxed text-muted">
                {welcome.market === "ZZ"
                  ? `We've set prices to ${geo.currency} (${geo.symbol}) for international visitors. You can change this anytime.`
                  : `It looks like you're visiting from ${geo.place}, so we've set prices to ${geo.currency} (${geo.symbol}). You can change this anytime.`}
              </p>
              <button
                ref={primaryRef}
                onClick={close}
                className="mt-7 w-full rounded-[var(--radius-card)] bg-accent py-3 font-medium text-surface transition-colors hover:bg-accent-strong"
              >
                Continue shopping
              </button>
              <button
                onClick={() => setChoosing(true)}
                className="mt-3 text-sm text-muted underline underline-offset-4 transition-colors hover:text-foreground"
              >
                Change country or currency
              </button>
            </>
          ) : (
            <>
              <h2 id="currency-welcome-title" className="mt-2 text-balance font-display text-2xl leading-snug">
                Shop in {geo.currencyName}?
              </h2>
              <p className="mx-auto mt-3 max-w-xs text-sm leading-relaxed text-muted">
                {welcome.market === "ZZ"
                  ? `Prices are currently in ${current.currencyName} (${current.symbol}). We can show them in ${geo.currency} (${geo.symbol}) for international visitors instead.`
                  : `It looks like you're visiting from ${geo.place}. Prices are currently in ${current.currencyName} (${current.symbol}).`}
              </p>
              <button
                ref={primaryRef}
                onClick={() => switchTo(welcome.market)}
                disabled={pending}
                className="mt-7 w-full rounded-[var(--radius-card)] bg-accent py-3 font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-60"
              >
                Switch to {geo.currency}
              </button>
              <button
                onClick={close}
                disabled={pending}
                className="mt-3 text-sm text-muted underline underline-offset-4 transition-colors hover:text-foreground disabled:opacity-60"
              >
                No thanks, keep {current.currency}
              </button>
            </>
          )}
        </div>
      </div>
    </OverlayPortal>
  );
}
