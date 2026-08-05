"use client";
import Link from "next/link";
import { useState } from "react";

interface Category { name: string; slug: string }

export function MobileNav({ categories }: { categories: Category[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="md:hidden">
      <button onClick={() => setOpen(true)} aria-label="Open menu" className="text-xl">☰</button>
      {open && (
        <div className="fixed inset-0 z-50">
          <div className="absolute inset-0 bg-black/30" onClick={() => setOpen(false)} />
          <nav className="absolute left-0 top-0 h-full w-72 bg-surface p-6" aria-label="Mobile">
            <button onClick={() => setOpen(false)} aria-label="Close menu" className="mb-6 text-muted">✕</button>
            <ul className="grid gap-3">
              <li><Link href="/" onClick={() => setOpen(false)} className="font-medium hover:text-accent">Home</Link></li>
              <li><Link href="/products" onClick={() => setOpen(false)} className="font-medium hover:text-accent">All Products</Link></li>
              <li><Link href="/skin-quiz" onClick={() => setOpen(false)} className="font-medium hover:text-accent">Skin Quiz</Link></li>
              <li><Link href="/blog" onClick={() => setOpen(false)} className="font-medium hover:text-accent">Blog</Link></li>
              <li className="mt-2 text-xs uppercase tracking-[0.16em] text-muted">Shop by Category</li>
              {categories.map((c) => (
                <li key={c.slug}>
                  <Link href={`/category/${c.slug}`} onClick={() => setOpen(false)} className="hover:text-accent">
                    {c.name}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      )}
    </div>
  );
}
