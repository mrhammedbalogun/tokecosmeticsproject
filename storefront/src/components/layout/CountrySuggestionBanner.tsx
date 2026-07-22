"use client";
import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { suggestionFor, isGeoSuggestionDismissed, dismissGeoSuggestion } from "@/lib/geo";
import { REST_OF_WORLD } from "@/lib/country";

// MUST stay in sync with the backend's active markets (GET /meta/countries/). Hardcoded on
// purpose to keep the proxy/banner path dependency-free; update this list if markets change.
const MARKET_CODES = ["NG", "GB", "US", "CA", "ZZ"];

// Human-friendly labels for the handful of market codes we suggest. Keeps the banner
// readable ("the United Kingdom" not "GB") without fetching the full markets list.
const MARKET_LABELS: Record<string, string> = {
  NG: "Nigeria",
  GB: "the United Kingdom",
  US: "the United States",
  CA: "Canada",
  [REST_OF_WORLD]: "International (USD)",
};

function labelForCode(code: string): string {
  return MARKET_LABELS[code] ?? code;
}

export function CountrySuggestionBanner({
  currentCountry,
  geoCountry,
}: {
  currentCountry: string;
  geoCountry: string;
}) {
  const router = useRouter();
  const [suggest, setSuggest] = useState<string | null>(null);
  const [pending, start] = useTransition();

  // Computed in an effect so the server and first client paint both render nothing (no
  // hydration mismatch). Re-runs when the current market changes — e.g. after an explicit
  // switch, which also sets the dismiss flag, so the banner then resolves to null.
  useEffect(() => {
    if (isGeoSuggestionDismissed()) {
      setSuggest(null);
      return;
    }
    const s = suggestionFor(undefined, geoCountry, MARKET_CODES);
    setSuggest(s === currentCountry ? null : s);
  }, [currentCountry, geoCountry]);

  if (!suggest || suggest === currentCountry) return null;

  // Reuse the exact mechanism CountrySwitcher uses to set the country cookie:
  // POST /api/country -> route handler writes the (non-httpOnly) cookie server-side, then
  // router.refresh() re-renders Server Components with the new market/prices. Only dismiss
  // and refresh on a successful write, so a failed request leaves the banner up to retry.
  function accept() {
    const code = suggest;
    if (!code) return;
    start(async () => {
      const res = await fetch("/api/country", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code }),
      });
      if (!res.ok) return;
      dismissGeoSuggestion();
      setSuggest(null);
      router.refresh();
    });
  }

  function dismiss() {
    dismissGeoSuggestion();
    setSuggest(null);
  }

  return (
    <div role="status" className="bg-accent/10 px-4 py-2 text-center text-sm">
      It looks like you&apos;re in {labelForCode(suggest)}. Shop in your local currency?{" "}
      <button
        onClick={accept}
        disabled={pending}
        className="font-medium text-accent-strong underline disabled:opacity-60"
      >
        Yes, switch
      </button>{" "}
      <button
        onClick={dismiss}
        disabled={pending}
        className="text-muted underline disabled:opacity-60"
      >
        No thanks
      </button>
    </div>
  );
}
