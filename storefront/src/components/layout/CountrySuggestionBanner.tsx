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
  const [pending, start] = useTransition();
  const [hidden, setHidden] = useState(false);

  // One-time post-mount reveal gate. The dismiss flag lives in localStorage (client-only), so
  // the server and the first (hydration) client render MUST output nothing to stay hydration-
  // safe; only after mount may we read localStorage and reveal the suggestion. This is the
  // "subscribe to a browser system" case the rule text white-lists. useSyncExternalStore (the
  // rule's suggested alternative) was tried but does not reliably re-read the client snapshot
  // post-hydration under Next 16 / React 19, so the banner never appeared — hence this gate.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time mount flag; reveal must wait for the client (localStorage) — see note above
    setMounted(true);
  }, []);

  // Read at render time (not cached in state) so an explicit CountrySwitcher choice, which
  // sets the dismiss flag then router.refresh()es, re-renders this to null on the next pass.
  const suggestion =
    mounted && !hidden && !isGeoSuggestionDismissed()
      ? suggestionFor(undefined, geoCountry, MARKET_CODES)
      : null;

  if (!suggestion || suggestion === currentCountry) return null;

  // Reuse the exact mechanism CountrySwitcher uses to set the country cookie:
  // POST /api/country -> route handler writes the (non-httpOnly) cookie server-side, then
  // router.refresh() re-renders Server Components with the new market/prices. Only dismiss
  // and refresh on a successful write, so a failed request leaves the banner up to retry.
  function accept() {
    if (!suggestion) return;
    const code = suggestion;
    start(async () => {
      const res = await fetch("/api/country", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code }),
      });
      if (!res.ok) return;
      dismissGeoSuggestion();
      setHidden(true);
      router.refresh();
    });
  }

  function dismiss() {
    dismissGeoSuggestion();
    setHidden(true);
  }

  return (
    <div role="status" className="bg-accent/10 px-4 py-2 text-center text-sm">
      It looks like you&apos;re in {labelForCode(suggestion)}. Shop in your local currency?{" "}
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
