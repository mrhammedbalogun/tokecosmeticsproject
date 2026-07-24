"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

interface Suggestion { name: string; slug: string }

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
      e.preventDefault(); setOpen(false); router.push(`/product/${items[active].slug}`);
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
        <ul id="search-listbox" role="listbox" aria-label="Product suggestions"
          className="absolute z-50 mt-2 w-full overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface shadow-lg">
          {items.map((s, i) => (
            <li key={s.slug} id={`search-opt-${i}`} role="option" aria-selected={i === active}>
              <button type="button"
                className={`block w-full px-4 py-2.5 text-left text-sm ${i === active ? "bg-beige" : "hover:bg-beige"}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => { setOpen(false); router.push(`/product/${s.slug}`); }}>
                {s.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
