"use client";
import { useRouter } from "next/navigation";
import { useOptimistic, useSyncExternalStore, useTransition } from "react";
import type { Market } from "@/lib/country";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY, labelFor, normalizeCountry } from "@/lib/country";
import { dismissGeoSuggestion } from "@/lib/geo";

/** The visitor's market, read in the BROWSER.
 *
 * Only for prerendered pages, where the server was not allowed to look. The `country`
 * cookie is deliberately NOT httpOnly (`api/country/route.ts`: "it is not a secret and
 * client UI reads it"), so this reads what is already there — it does not weaken
 * anything, and it touches none of the httpOnly cookies beside it.
 *
 * `useSyncExternalStore`, not `useState` + `useEffect`, and the difference matters twice.
 * It is the hook for reading a value that lives OUTSIDE React — the same one
 * `CardHoverImage` uses for a media query — so the server snapshot is `undefined` by
 * construction and hydration cannot mismatch. And because the snapshot is re-read on
 * every render rather than captured once, switching market re-reads the cookie the
 * transition just wrote: a `useEffect` that ran only on mount would hold the OLD market,
 * and `useOptimistic` would fall back to it the moment the transition settled, snapping
 * the select back to where it started.
 */
const neverChangesOnItsOwn = () => () => {};

function readCountryCookie(): string | undefined {
  const raw = document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${COUNTRY_COOKIE}=`))
    ?.split("=")[1];
  return raw ? decodeURIComponent(raw) : undefined;
}

function useCookieCountry(codes: string[]): string | undefined {
  return useSyncExternalStore(
    neverChangesOnItsOwn,
    () => normalizeCountry(readCountryCookie(), codes) || DEFAULT_COUNTRY,
    // Server and first hydration render: unknown. Matches the prerendered HTML exactly.
    () => undefined,
  );
}

export function CountrySwitcher({
  markets,
  current,
  onChanged,
  className = "flex items-center gap-1 text-sm",
}: {
  markets: Market[];
  /** The server-resolved market. Undefined on a prerendered page, where the cookie is
   *  read in the browser instead — see `useCookieCountry`. */
  current?: string;
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
  const clientCountry = useCookieCountry(markets.map((m) => m.code));
  // Server answer wins when there is one; otherwise the browser's, and DEFAULT_COUNTRY
  // only until the effect runs. The select is never renderless.
  const [value, setValue] = useOptimistic(current ?? clientCountry ?? DEFAULT_COUNTRY);

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
