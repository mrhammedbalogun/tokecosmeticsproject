export default async function CmsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <section className="mx-auto max-w-3xl px-4 py-16"><h1 className="font-display text-4xl capitalize">{slug.replace(/-/g, " ")}</h1><p className="mt-4 text-muted">CMS content arrives in Plan-19.</p></section>;
}
