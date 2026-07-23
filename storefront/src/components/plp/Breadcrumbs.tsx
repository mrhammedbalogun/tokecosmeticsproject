import Link from "next/link";

export interface Crumb { name: string; path: string }

export function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="text-sm text-muted">
      <ol className="flex flex-wrap items-center gap-1.5">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <li key={c.path} className="flex items-center gap-1.5">
              {i > 0 && <span aria-hidden>/</span>}
              {last
                ? <span aria-current="page" className="text-foreground">{c.name}</span>
                : <Link href={c.path} className="hover:text-accent">{c.name}</Link>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
