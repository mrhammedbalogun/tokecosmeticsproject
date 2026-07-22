"use client";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import type { Market } from "@/lib/country";
import { labelFor } from "@/lib/country";
import { dismissGeoSuggestion } from "@/lib/geo";

export function CountrySwitcher({ markets, current }: { markets: Market[]; current: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [value, setValue] = useState(current);

  function change(code: string) {
    setValue(code);
    // An explicit choice supersedes any geo suggestion — suppress the banner for good.
    dismissGeoSuggestion();
    start(async () => {
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
