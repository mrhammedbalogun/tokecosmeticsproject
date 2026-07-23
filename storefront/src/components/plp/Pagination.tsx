import Link from "next/link";
import { plpHref, type PlpState } from "@/components/plp/plpParams";

export function Pagination({ base, state, count, pageSize = 24 }: {
  base: string; state: PlpState; count: number; pageSize?: number;
}) {
  const pages = Math.ceil(count / pageSize);
  if (pages <= 1) return null;
  const page = state.page;
  return (
    <nav aria-label="Pagination" className="mt-10 flex items-center justify-center gap-2">
      {page > 1 && (
        <Link rel="prev" href={plpHref(base, state, { page: page - 1 })}
          className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent">← Prev</Link>
      )}
      <span className="px-3 text-sm text-muted">Page {page} of {pages}</span>
      {page < pages && (
        <Link rel="next" href={plpHref(base, state, { page: page + 1 })}
          className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent">Next →</Link>
      )}
    </nav>
  );
}
