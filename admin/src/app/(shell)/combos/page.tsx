import type { Metadata } from "next";
import Link from "next/link";
import { Pagination } from "@/components/Pagination";
import { ComboTable } from "@/components/combo/ComboTable";
import { ApiError } from "@/lib/api";
import { comboQueryString, isComboStatus, STATUSES, type ComboPage } from "@/lib/combos";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Combos" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/combos";

/**
 * `/combos` — the bundle list, behind `products.manage`.
 *
 * FILTERS LIVE IN THE URL here, which is the opposite of the builder's local state and
 * for the reason the products list gives: this is a list, not a form. There is nothing
 * unsaved to lose, and a shareable "here is the one I mean" link is worth having.
 */
export default async function CombosPage({ searchParams }: { searchParams: SearchParams }) {
  await requireAdmin(PATH);

  const raw = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (typeof value === "string") raw.set(key, value);
    else if (Array.isArray(value) && value[0] !== undefined) raw.set(key, value[0]);
  }
  // Blank is ABSENT, not empty: a GET form submits every field it contains, so without
  // this an untouched form sends `?search=&status=` — two filters that match everything.
  const search = raw.get("search")?.trim() || undefined;
  const statusRaw = raw.get("status")?.trim() ?? "";
  const status = isComboStatus(statusRaw) ? statusRaw : undefined;
  const page = Math.max(1, Number(raw.get("page")) || 1);

  let data: ComboPage | null = null;
  let error: string | null = null;
  try {
    const qs = comboQueryString({ search, status, page });
    data = await fetchWithAuthOrBounce<ComboPage>(`/admin/combos/${qs ? `?${qs}` : ""}`, PATH);
  } catch (e) {
    // `redirect()` throws, so a bare catch-all would swallow the renewal bounce.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing products."
        : "The combo list could not be loaded.";
  }

  const rows = data?.results ?? [];

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Combos</h1>
          <p className="mt-1 text-sm text-muted">
            Products sold together at one price. They appear on{" "}
            <span className="font-mono text-xs">/combo</span> when set to Active.
          </p>
        </div>
        <Link
          href="/combos/new"
          className="rounded bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >
          New combo
        </Link>
      </div>

      <form method="get" className="mt-6 flex flex-wrap items-end gap-3">
        <label className="text-xs text-muted">
          Search
          <input
            type="search"
            name="search"
            defaultValue={search ?? ""}
            placeholder="Combo name"
            className="mt-1 block w-56 rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
          />
        </label>
        <label className="text-xs text-muted">
          Status
          <select
            name="status"
            defaultValue={status ?? ""}
            className="mt-1 block w-36 rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
          >
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s[0].toUpperCase() + s.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          className="rounded border border-line bg-surface px-3 py-1.5 text-sm hover:border-accent"
        >
          Filter
        </button>
      </form>

      {error ? (
        <p className="mt-6 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
          {error}
        </p>
      ) : (
        <>
          <div className="mt-4">
            <ComboTable rows={rows} />
          </div>
          {data && data.count > rows.length && (
            <div className="mt-4">
              <Pagination
                basePath={PATH}
                page={page}
                total={data.count}
                buildQuery={(p) => comboQueryString({ search, status, page: p })}
                label="Combos"
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
