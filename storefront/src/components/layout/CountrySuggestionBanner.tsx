"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { suggestionFor } from "@/lib/geo";
import { REST_OF_WORLD } from "@/lib/country";

const MARKET_CODES = ["NG", "GB", "US", "CA", "ZZ"];
const DISMISS_KEY = "toke-geo-dismissed";

// Human-friendly labels for the handful of market codes we suggest. Keeps the banner
// readable ("United Kingdom" not "GB") without fetching the full markets list.
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

export function CountrySuggestionBanner({ currentCountry }: { currentCountry: string }) {
  const router = useRouter();
  const [suggest, setSuggest] = useState<string | null>(null);

  useEffect(() => {
    if (localStorage.getItem(DISMISS_KEY)) return;
    const geo = document.querySelector<HTMLMetaElement>('meta[name="x-geo-country"]')?.content;
    const s = suggestionFor(undefined, geo, MARKET_CODES);
    setSuggest(s === currentCountry ? null : s);
  }, [currentCountry]);

  if (!suggest || suggest === currentCountry) return null;

  // Reuse the exact mechanism CountrySwitcher uses to set the country cookie:
  // POST /api/country -> route handler writes the (non-httpOnly) cookie server-side,
  // then router.refresh() re-renders Server Components with the new market/prices.
  async function accept() {
    if (!suggest) return;
    try {
      await fetch("/api/country", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code: suggest }),
      });
    } finally {
      localStorage.setItem(DISMISS_KEY, "1");
      setSuggest(null);
      router.refresh();
    }
  }

  function dismiss() {
    localStorage.setItem(DISMISS_KEY, "1");
    setSuggest(null);
  }

  return (
    <div className="bg-accent/10 px-4 py-2 text-center text-sm">
      It looks like you&apos;re in {labelForCode(suggest)}. Shop in your local currency?{" "}
      <button onClick={accept} className="font-medium text-accent underline">
        Yes, switch
      </button>{" "}
      <button onClick={dismiss} className="text-muted underline">
        No thanks
      </button>
    </div>
  );
}
