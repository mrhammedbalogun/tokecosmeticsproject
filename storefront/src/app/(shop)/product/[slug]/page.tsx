export default async function ProductPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <section className="mx-auto max-w-7xl px-4 py-16"><h1 className="font-display text-4xl">Product: {slug}</h1><p className="mt-4 text-muted">Detail page arrives in Plan-13.</p></section>;
}
