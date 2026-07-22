/** Typed, tagged catalog/search/review fetchers. Server-side only (uses apiFetch).
 * Cache strategy: pages render dynamically (they read the country cookie), so
 * caching lives in the fetch data-cache — short revalidate + tags, invalidated by
 * POST /api/revalidate (Task 12). Backend also caches catalog GETs for 60 s. */
import { apiFetch } from "@/lib/api";

// ---------- types (mirror backend serializers; regenerate api-types for drift) ----------
export interface ProductCard {
  name: string; slug: string;
  brand: string | null;           // the brand SLUG (SlugRelatedField), not the name
  is_featured: boolean;
  from_price: string | null;      // money string — display verbatim
  currency: string;
  image: string | null; hover_image: string | null;   // relative /media URLs
  default_variant_id: number | null; default_sku: string | null;
  rating_avg: string;             // "4.50"
  rating_count: number;
}
export interface Paginated<T> {
  count: number; next: string | null; previous: string | null; results: T[];
}
export interface VariantPrice {
  amount: string; compare_at: string | null; currency: string;
  tax_rate: string; prices_include_tax: boolean;
}
export interface Variant {
  id: number; sku: string; name: string;
  option_values: Record<string, string>;
  price: VariantPrice | null; in_stock: boolean; low_stock: boolean;
}
export interface ProductDetail {
  name: string; slug: string;
  brand: { name: string; slug: string; logo: string | null; description: string } | null;
  description: string; short_description: string;
  ingredients: string; directions: string; warnings: string;
  specs: { label: string; value: string }[];
  faqs: { q: string; a: string }[];
  seo_title: string; seo_description: string;
  variants: Variant[];
  images: { url: string; alt: string; variant_id: number | null }[];
  related: ProductCard[];
  rating_avg: string; rating_count: number;
}
export interface CategoryNode {
  name: string; slug: string; image: string | null; sort_order: number;
  children: CategoryNode[];
}
export interface BrandRow { name: string; slug: string; logo: string | null; description: string }
export interface CollectionRow { name: string; slug: string; description: string; image: string | null }
export interface ReviewRow { rating: number; title: string; body: string; author: string; created_at: string }

// ---------- product list query builder (URL params are untrusted input) ----------
export interface ProductListParams {
  category?: string; brand?: string; tag?: string; collection?: string;
  price_min?: string; price_max?: string;
  ordering?: "newest" | "price_asc" | "price_desc" | "best_selling";
  page?: number;
}
const LIST_KEYS: (keyof ProductListParams)[] = [
  "category", "brand", "tag", "collection", "price_min", "price_max", "ordering", "page",
];

export function buildProductQuery(params: ProductListParams): string {
  const qs = new URLSearchParams();
  for (const key of LIST_KEYS) {
    const v = params[key];
    if (v === undefined || v === "" || (key === "page" && Number(v) <= 1)) continue;
    qs.set(key, String(v));
  }
  return qs.toString();
}

// ---------- fetchers ----------
const CATALOG_REVALIDATE = 60; // matches the backend's own catalog cache TTL

export async function getProducts(params: ProductListParams, country: string) {
  const q = buildProductQuery(params);
  return apiFetch<Paginated<ProductCard>>(`/products/${q ? `?${q}` : ""}`, {
    country, next: { revalidate: CATALOG_REVALIDATE, tags: ["catalog"] },
  });
}

export async function getProduct(slug: string, country: string) {
  return apiFetch<ProductDetail>(`/products/${slug}/`, {
    country, next: { revalidate: CATALOG_REVALIDATE, tags: ["catalog", `product:${slug}`] },
  });
}

export async function getCategoryTree(country: string) {
  return apiFetch<CategoryNode[]>("/categories/", {
    country, next: { revalidate: 3600, tags: ["catalog"] },
  });
}

export async function getBrands(country: string) {
  return apiFetch<BrandRow[]>("/brands/", {
    country, next: { revalidate: 3600, tags: ["catalog"] },
  });
}

export async function getCollection(slug: string, country: string) {
  return apiFetch<CollectionRow>(`/collections/${slug}/`, {
    country, next: { revalidate: 3600, tags: ["catalog"] },
  });
}

export interface SearchParams {
  q?: string; category?: string; brand?: string;
  price_min?: string; price_max?: string; in_stock?: "1";
  sort?: "price_asc" | "price_desc" | "newest"; page?: number;
}
export async function searchProducts(params: SearchParams, country: string) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "" || (k === "page" && Number(v) <= 1)) continue;
    qs.set(k, String(v));
  }
  // /search/ is throttled 30/min/IP — server-side calls only, never poll it.
  return apiFetch<Paginated<ProductCard>>(`/search/?${qs.toString()}`, {
    country, cache: "no-store",
  });
}

export async function getReviews(slug: string) {
  return apiFetch<ReviewRow[]>(`/products/${slug}/reviews/`, {
    next: { revalidate: 300, tags: [`product:${slug}`] },
  });
}

// ---------- category tree helpers ----------
export function findCategory(
  tree: CategoryNode[], slug: string, ancestors: CategoryNode[] = [],
): { node: CategoryNode; ancestors: CategoryNode[] } | null {
  for (const node of tree) {
    if (node.slug === slug) return { node, ancestors };
    const hit = findCategory(node.children, slug, [...ancestors, node]);
    if (hit) return hit;
  }
  return null;
}

export function flattenCategories(tree: CategoryNode[]): CategoryNode[] {
  return tree.flatMap((n) => [n, ...flattenCategories(n.children)]);
}
