export default async function CategoryPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <section className="mx-auto max-w-7xl px-4 py-16"><h1 className="font-display text-4xl">Category: {slug}</h1><p className="mt-4 text-muted">Listing arrives in Plan-13.</p></section>;
}
