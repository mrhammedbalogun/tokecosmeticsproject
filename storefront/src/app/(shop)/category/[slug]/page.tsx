import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { fetchPlpPage, findCategory, getBrands, getCategoryTree } from "@/lib/catalog";
import { mediaUrl } from "@/lib/media";
import { breadcrumbJsonLd, pageMetadata } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";
import { parsePlpParams } from "@/components/plp/plpParams";
import { Breadcrumbs, type Crumb } from "@/components/plp/Breadcrumbs";
import { ProductGrid } from "@/components/plp/ProductGrid";
import { FiltersBar } from "@/components/plp/FiltersBar";
import { Pagination } from "@/components/plp/Pagination";

type Params = Promise<{ slug: string }>;
type Search = Promise<Record<string, string | string[] | undefined>>;

/** Resolve a category by slug. The tree fetch is ROUTING-CRITICAL: if it fails
 * (5xx / network blip) we must NOT swallow the error, because collapsing it to an
 * empty tree would make findCategory miss and the caller notFound() — turning a
 * transient backend fault into a hard 404 on a canonical, indexable URL (crawlers
 * retry 5xx but can drop 404s). So let a real error throw (→ 500). A `null` here
 * means the tree loaded fine but the slug genuinely does not exist → notFound(). */
async function loadCategory(slug: string, country: string) {
  const tree = await getCategoryTree(country);
  return findCategory(tree, slug);
}

export async function generateMetadata(
  { params, searchParams }: { params: Params; searchParams: Search },
): Promise<Metadata> {
  const { slug } = await params;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const hit = await loadCategory(slug, country);
  if (!hit) return { title: "Category not found" };
  const raw = await searchParams;
  // Category seo_title/seo_description are NOT exposed by the API yet (Plan-13
  // flagged risk) — a name-based template stands in until a later backend change.
  return pageMetadata({
    title: `${hit.node.name} — Skincare & Beauty`,
    description: `Shop ${hit.node.name.toLowerCase()} by Toke Cosmetics — premium, science-backed care for melanin-rich skin. Ships from Nigeria worldwide.`,
    path: `/category/${slug}`,
    searchParams: Object.fromEntries(
      Object.entries(raw).map(([k, v]) => [k, Array.isArray(v) ? v[0] : v]),
    ),
    image: mediaUrl(hit.node.image),
  });
}

export default async function CategoryPage(
  { params, searchParams }: { params: Params; searchParams: Search },
) {
  const { slug } = await params;
  const state = parsePlpParams(await searchParams);
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const hit = await loadCategory(slug, country);
  if (!hit) notFound();

  const [page, brands] = await Promise.all([
    fetchPlpPage({ ...state, category: slug }, country),
    getBrands(country).catch(() => []),
  ]);

  const crumbs: Crumb[] = [
    { name: "Home", path: "/" },
    ...hit.ancestors.map((a) => ({ name: a.name, path: `/category/${a.slug}` })),
    { name: hit.node.name, path: `/category/${slug}` },
  ];

  return (
    <section className="mx-auto max-w-7xl px-4 py-10">
      <JsonLd data={breadcrumbJsonLd(crumbs)} />
      <Breadcrumbs crumbs={crumbs} />
      <h1 className="mt-4 font-display text-4xl">{hit.node.name}</h1>
      {hit.node.children.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {hit.node.children.map((c) => (
            <Link key={c.slug} href={`/category/${c.slug}`}
              className="rounded-full border border-line px-4 py-1.5 text-sm transition hover:border-accent hover:text-accent">
              {c.name}
            </Link>
          ))}
        </div>
      )}
      <div className="mt-6">
        <FiltersBar base={`/category/${slug}`} state={state} brands={brands} resultCount={page.count} />
      </div>
      <div className="mt-6">
        <ProductGrid products={page.results} />
      </div>
      <Pagination base={`/category/${slug}`} state={state}
        hasPrev={page.previous !== null} hasNext={page.next !== null} />
    </section>
  );
}
