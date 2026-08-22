"use client";

/**
 * The store directory's filter bar (Plan-42).
 *
 * A PLAIN GET FORM, like `ProductFilterForm` — submitting navigates to
 * `?country=…&state_region=…&status=…`, which is the URL shape the page already reads.
 * Bookmarkable, survives a reload, and the back button undoes a filter.
 *
 * IT IS A CLIENT COMPONENT ONLY BECAUSE TWO OF ITS SELECTS DEPEND ON A THIRD. Country
 * decides which states are offered and state decides which LGAs are — that cascade is
 * state, and `ProductFilterForm`'s two independent fields did not need any. Everything
 * else about it is the same form: no controlled text input, no fetch, no client-side
 * filtering of the table (the backend filters in SQL; a browser-side filter would only
 * narrow the page on screen and quietly lie about the rest).
 *
 * `page` is deliberately NOT a hidden field. Changing a filter must return to page 1 —
 * keeping page 3 while narrowing is how somebody lands on an empty page and concludes
 * their search matched nothing.
 */
import { useMemo, useState } from "react";
import Link from "next/link";
import type { CountryRef } from "@/lib/reference";
import type { RegionRow } from "@/lib/regions";
import {
  STATUSES,
  STORE_TYPES,
  statusLabel,
  storeTypeLabel,
  type StoreFilters,
} from "@/lib/stores";

const FIELD =
  "mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

export function StoreFilterForm({
  filters,
  countries,
  regions,
}: {
  filters: StoreFilters;
  countries: CountryRef[];
  regions: RegionRow[];
}) {
  const [country, setCountry] = useState(filters.country ?? "");
  const [stateId, setStateId] = useState<string>(
    filters.state_region ? String(filters.state_region) : "",
  );

  const countryRef = countries.find((c) => c.code === country) ?? null;
  const states = useMemo(
    () =>
      regions
        .filter((r) => r.level === "state" && (!country || r.country_code === country))
        .sort((a, b) => a.name.localeCompare(b.name)),
    [regions, country],
  );
  const areas = useMemo(
    () =>
      regions
        .filter((r) => r.level === "area" && String(r.parent) === stateId)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [regions, stateId],
  );

  return (
    <form
      method="get"
      className="mb-4 grid gap-3 rounded-[var(--radius-card)] border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      <label className="block text-xs text-muted lg:col-span-2">
        Search
        {/* Naming the phone number because the backend also matches it by SUFFIX — a
            number typed the way it is printed on the shop's door finds the row stored
            as E.164, and nothing on screen would otherwise suggest that works. */}
        <input
          type="search"
          name="q"
          defaultValue={filters.q ?? ""}
          placeholder="name, address or phone…"
          className={FIELD}
        />
      </label>

      <label className="block text-xs text-muted">
        Country
        <select
          name="country"
          value={country}
          onChange={(e) => {
            setCountry(e.target.value);
            // A state id from the old country would narrow the list to nothing.
            setStateId("");
          }}
          className={FIELD}
        >
          <option value="">Any</option>
          {countries.map((c) => (
            <option key={c.code} value={c.code}>
              {c.name}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-muted">
        {countryRef?.state_label || "State"}
        <select
          name="state_region"
          value={stateId}
          onChange={(e) => setStateId(e.target.value)}
          className={FIELD}
        >
          <option value="">Any</option>
          {states.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>

      {/* Only where the chosen state has districts. An always-present dropdown with no
          options reads as broken, and `parseStoreFilters` drops an area without a state
          anyway. */}
      <label className="block text-xs text-muted">
        {countryRef?.area_label || "Area"}
        <select
          name="area_region"
          defaultValue={filters.area_region ? String(filters.area_region) : ""}
          disabled={areas.length === 0}
          className={FIELD}
        >
          <option value="">{areas.length === 0 ? "—" : "Any"}</option>
          {areas.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-muted">
        Store type
        <select
          name="store_type"
          defaultValue={filters.store_type ?? ""}
          className={FIELD}
        >
          <option value="">Any</option>
          {STORE_TYPES.map((t) => (
            <option key={t} value={t}>
              {storeTypeLabel(t)}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-muted">
        Status
        <select name="status" defaultValue={filters.status ?? ""} className={FIELD}>
          {/* Blank is NOT "all" — with no status the API hides archived rows, which is
              the right default view of a directory. The label says so. */}
          <option value="">Live directory</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {statusLabel(s)}
            </option>
          ))}
        </select>
      </label>

      <div className="flex items-end gap-2">
        <button
          type="submit"
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >
          Filter
        </button>
        {/* A link, not `type="reset"`: reset restores the fields to the values the page
            was rendered with, which on a filtered page is the filter itself. */}
        <Link
          href="/find-stores"
          className="text-sm text-muted underline-offset-2 hover:underline"
        >
          Clear
        </Link>
      </div>
    </form>
  );
}
