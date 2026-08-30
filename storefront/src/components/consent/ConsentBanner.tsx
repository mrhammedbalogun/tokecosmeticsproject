"use client";
/**
 * The cookie banner (Plan-44).
 *
 * ── THREE THINGS HERE ARE COMPLIANCE, NOT DESIGN ────────────────────────────────────
 *
 * 1. **"Reject all" is as prominent as "Accept all".** Same size, same weight, same
 *    row, neither greyed. A reject button that is harder to find than accept is the
 *    exact dark pattern the ICO and the EDPB have both ruled against, and it is the
 *    single most common way a banner fails an audit.
 * 2. **Nothing is pre-ticked.** In the "Choose" panel both switches start from the
 *    CURRENT state, which for a first-time visitor in a consent-required country is off.
 * 3. **It does not block the page.** A bar, not a modal: consent must be freely given,
 *    and a visitor who cannot read the shop until they agree has not freely agreed. It
 *    also means the banner cannot cost a sale by trapping someone mid-checkout.
 *
 * Withdrawal is via the same banner, reopened from the footer's "Cookie choices" link —
 * withdrawing has to be as easy as granting.
 */
import { useState } from "react";
import Link from "next/link";
import { useConsent } from "@/components/consent/ConsentProvider";

export function ConsentBanner() {
  const { showBanner, consent, accept, reject, save } = useConsent();
  const [choosing, setChoosing] = useState(false);
  const [analytics, setAnalytics] = useState(consent.analytics);
  const [marketing, setMarketing] = useState(consent.marketing);

  if (!showBanner) return null;

  return (
    <div
      role="dialog"
      aria-label="Cookie choices"
      aria-live="polite"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/95 px-4 py-4 shadow-[0_-8px_24px_rgba(0,0,0,0.08)] backdrop-blur sm:px-6"
    >
      <div className="mx-auto flex max-w-5xl flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-sm text-muted">
          <p className="font-medium text-foreground">We use cookies</p>
          <p className="mt-1 max-w-2xl">
            Some keep the shop working — your bag, your currency, staying signed in. Others
            let us measure our adverts on Facebook, Instagram, TikTok, Snapchat and Google.
            You choose.{" "}
            <Link href="/page/privacy" className="underline hover:text-foreground">
              Privacy policy
            </Link>
          </p>
        </div>

        {/* Equal prominence, deliberately — see the file docstring. */}
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setChoosing((v) => !v)}
            aria-expanded={choosing}
            className="rounded-full border border-line px-4 py-2 text-sm text-muted transition-colors hover:text-foreground"
          >
            Choose
          </button>
          <button
            type="button"
            onClick={reject}
            className="rounded-full border border-foreground px-5 py-2 text-sm font-medium text-foreground transition-colors hover:bg-foreground hover:text-surface"
          >
            Reject all
          </button>
          <button
            type="button"
            onClick={accept}
            className="rounded-full border border-foreground bg-foreground px-5 py-2 text-sm font-medium text-surface transition-colors hover:opacity-90"
          >
            Accept all
          </button>
        </div>
      </div>

      {choosing && (
        <div className="mx-auto mt-4 max-w-5xl border-t border-line pt-4">
          <ul className="space-y-3 text-sm">
            <li className="flex items-start justify-between gap-4">
              <div>
                <p className="font-medium text-foreground">Strictly necessary</p>
                <p className="text-muted">
                  Your bag, your currency, signing in and paying. The shop cannot work
                  without these, so they cannot be switched off.
                </p>
              </div>
              <span className="shrink-0 pt-1 text-xs uppercase tracking-widest text-muted">
                Always on
              </span>
            </li>

            <ConsentToggle
              label="Measurement"
              description="How many people reach a page, and where they stopped. Helps us fix the shop."
              checked={analytics}
              onChange={setAnalytics}
            />
            <ConsentToggle
              label="Advertising"
              description="Lets Facebook, Instagram, TikTok, Snapchat and Google tell us which advert brought you here, and show you products you looked at."
              checked={marketing}
              onChange={setMarketing}
            />
          </ul>

          <div className="mt-4 flex justify-end">
            <button
              type="button"
              onClick={() => save({ analytics, marketing })}
              className="rounded-full border border-foreground bg-foreground px-5 py-2 text-sm font-medium text-surface transition-colors hover:opacity-90"
            >
              Save my choices
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ConsentToggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <li className="flex items-start justify-between gap-4">
      <div>
        <p className="font-medium text-foreground">{label}</p>
        <p className="text-muted">{description}</p>
      </div>
      <label className="flex shrink-0 cursor-pointer items-center gap-2 pt-1">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 accent-foreground"
        />
        <span className="sr-only">{label}</span>
        <span aria-hidden className="text-xs uppercase tracking-widest text-muted">
          {checked ? "On" : "Off"}
        </span>
      </label>
    </li>
  );
}
