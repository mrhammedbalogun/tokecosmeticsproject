"use client";
import { useRouter } from "next/navigation";
import { useOptimistic, useTransition } from "react";
import type { Market } from "@/lib/country";
import { labelFor } from "@/lib/country";
import { dismissGeoSuggestion } from "@/lib/geo";

export function CountrySwitcher({ markets, current }: { markets: Market[]; current: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  // Optimistic mirror of the server-derived country: shows the picked value instantly
  // while the POST+refresh is in flight, then follows `current`. Plain useState(current)
  // froze the mount value, so a switch made ELSEWHERE (the welcome popup) updated the
  // prices but left this select stale until a full reload.
  const [value, setValue] = useOptimistic(current);

  function change(code: string) {
    // An explicit choice supersedes any geo suggestion — suppress the popup for good.
    // Dismissing before the POST resolves is intentional: an explicit pick signals intent regardless of the request outcome.
    dismissGeoSuggestion();
    start(async () => {
      setValue(code); // inside the transition, as useOptimistic requires
      await fetch("/api/country", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ code }),
      });
      router.refresh(); // re-render server components with the new country -> new prices
    });
  }

  return (
    <label className="flex items-center gap-1 text-sm">
      <span className="sr-only">Country and currency</span>
      <select
        value={value}
        disabled={pending}
        onChange={(e) => change(e.target.value)}
        className="bg-transparent text-foreground focus:outline-none"
      >
        {markets.map((m) => (
          <option key={m.code} value={m.code}>
            {labelFor(m)} — {m.currency.code}
          </option>
        ))}
      </select>
    </label>
  );
}
