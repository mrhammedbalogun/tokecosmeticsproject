export default async function SearchPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q } = await searchParams;
  return <section className="mx-auto max-w-7xl px-4 py-16"><h1 className="font-display text-4xl">Search{q ? `: ${q}` : ""}</h1><p className="mt-4 text-muted">Search results arrive in Plan-13.</p></section>;
}
