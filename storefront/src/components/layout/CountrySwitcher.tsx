"use client";
import { useRouter } from "next/navigation";
import { useOptimistic, useTransition } from "react";
import type { Market } from "@/lib/country";
import { labelFor } from "@/lib/country";
import { dismissGeoSuggestion } from "@/lib/geo";

/**
 * Country + currency picker.
 *
 * A NATIVE `<select>` SIZES ITSELF TO ITS LONGEST OPTION, not to the selected one. With
 * "International — USD" in the list that came to 198px, which on a 390px phone was wider
 * than everything else in the header put together: it squeezed the Toke logo to 0×0 and
 * pushed the cart button off the right edge (measured 2026-08-16). The header now renders
 * this only from `lg` up and the mobile drawer carries it instead, where a 198px control
 * is simply a row.
 */
export function CountrySwitcher({
  markets,
  current,
  onChanged,
  className = "flex items-center gap-1 text-sm",
}: {
  markets: Market[];
  current: string;
  /** Fired after a market is picked — the drawer uses it to close itself, so choosing a
   *  country does not leave the customer staring at the menu they chose it from. */
  onChanged?: () => void;
  className?: string;
}) {
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
    onChanged?.();
  }

  return (
    <label className={className}>
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
