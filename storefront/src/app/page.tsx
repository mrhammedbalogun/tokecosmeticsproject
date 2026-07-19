export default function Home() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="font-display text-5xl text-foreground">Toke Cosmetics</h1>
      <p className="mt-3 text-lg text-muted">Premium beauty. Design-system preview.</p>
      <div className="mt-10 flex gap-3">
        <span className="h-12 w-12 rounded-full" style={{ background: "var(--color-accent)" }} />
        <span className="h-12 w-12 rounded-full" style={{ background: "var(--color-leaf)" }} />
        <span className="h-12 w-12 rounded-full" style={{ background: "var(--color-gold)" }} />
        <span className="h-12 w-12 rounded-full" style={{ background: "var(--color-beige)" }} />
        <span className="h-12 w-12 rounded-full border border-line" style={{ background: "var(--color-cream)" }} />
        <span className="h-12 w-12 rounded-full" style={{ background: "var(--color-ink)" }} />
      </div>
      <button className="mt-8 rounded-[var(--radius-card)] bg-accent px-6 py-3 text-surface hover:bg-accent-strong transition-colors">
        Add to bag
      </button>
      <p className="mt-6 text-2xl font-medium">₦12,500.00</p>
    </main>
  );
}
