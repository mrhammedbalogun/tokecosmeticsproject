"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

/** One row of the dropdown.
 *
 *  `type` DECIDES THE LINK, and it is optional for one reason: the API caches nothing
 *  here but the backend and this app ship separately (a push for the frontends, a tag for
 *  the API), so a build of this file can be handed a payload from before bundles were
 *  suggested. Everything in that payload was a product, which is exactly what the
 *  fallback below assumes. */
interface Suggestion { name: string; slug: string; type?: "product" | "combo" }

/** Where a suggestion goes. A combo slug and a product slug are SEPARATE namespaces and
 *  may collide, so guessing sends the shopper to a 404. */
function hrefFor(s: Suggestion) {
  return s.type === "combo" ? `/combo/${s.slug}` : `/product/${s.slug}`;
}

export function SearchBar() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const debounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const rootRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    clearTimeout(debounce.current);
    const query = q.trim();
    // Abort the previous request on every keystroke so an out-of-order (stale)
    // response can never overwrite fresh results or re-open a cleared box.
    const controller = new AbortController();
    // State updates live in the deferred callback (not the effect body) — a short
    // query resets on the next tick (0ms), a real one debounces at 300ms.
    debounce.current = setTimeout(async () => {
      if (query.length < 2) { setItems([]); setOpen(false); return; }
      try {
        const res = await fetch(`/api/search/suggest?q=${encodeURIComponent(query)}`,
          { signal: controller.signal });
        if (controller.signal.aborted) return;             // superseded while awaiting
        const data: Suggestion[] = res.ok ? await res.json() : [];
        if (controller.signal.aborted) return;             // superseded while parsing
        setItems(data); setOpen(data.length > 0); setActive(-1);
      } catch { /* aborted or network error: leave prior state untouched */ }
    }, query.length < 2 ? 0 : 300);
    return () => { clearTimeout(debounce.current); controller.abort(); };
  }, [q]);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  function onKeyDown(e: React.KeyboardEvent) {
    if (!open) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, -1)); }
    else if (e.key === "Enter" && active >= 0) {
      e.preventDefault(); setOpen(false); router.push(hrefFor(items[active]));
    } else if (e.key === "Escape") setOpen(false);
  }

  return (
    <form
      ref={rootRef}
      role="search"
      className="relative hidden flex-1 md:block"
      onSubmit={(e) => {
        e.preventDefault(); setOpen(false);
        if (q.trim()) router.push(`/search?q=${encodeURIComponent(q.trim())}`);
      }}
    >
      <label className="sr-only" htmlFor="site-search">Search products</label>
      <input
        id="site-search" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKeyDown}
        role="combobox" aria-expanded={open} aria-controls="search-listbox" aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `search-opt-${active}` : undefined}
        placeholder="Search products…" autoComplete="off"
        className="w-full rounded-full border border-line bg-surface px-4 py-2 text-sm outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/40"
      />
      {open && (
        <ul id="search-listbox" role="listbox" aria-label="Search suggestions"
          className="absolute z-50 mt-2 w-full overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface shadow-lg">
          {items.map((s, i) => (
            // Keyed on type AND slug: the two namespaces are separate, so a combo and a
            // product may legitimately share a slug and appear in the same list.
            <li key={`${s.type ?? "product"}-${s.slug}`} id={`search-opt-${i}`} role="option" aria-selected={i === active}>
              <button type="button"
                className={`flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm ${i === active ? "bg-beige" : "hover:bg-beige"}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => { setOpen(false); router.push(hrefFor(s)); }}>
                <span className="truncate">{s.name}</span>
                {s.type === "combo" && (
                  // Said in words, not colour alone: a bundle behaves differently from a
                  // product once clicked, and the shopper should know before they click.
                  <span className="ml-auto shrink-0 rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-accent">
                    Bundle
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
