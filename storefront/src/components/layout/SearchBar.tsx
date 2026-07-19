"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function SearchBar() {
  const router = useRouter();
  const [q, setQ] = useState("");
  return (
    <form
      onSubmit={(e) => { e.preventDefault(); if (q.trim()) router.push(`/search?q=${encodeURIComponent(q)}`); }}
      role="search"
      className="hidden flex-1 md:block"
    >
      <label className="sr-only" htmlFor="site-search">Search products</label>
      <input
        id="site-search" value={q} onChange={(e) => setQ(e.target.value)}
        placeholder="Search products…"
        className="w-full rounded-full border border-line bg-surface px-4 py-2 text-sm"
      />
    </form>
  );
}
