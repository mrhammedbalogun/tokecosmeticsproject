/** Metadata for a "Shop By Edit" listing — one implementation, three routes.
 *
 * Split out of `shop-edits.ts` so that file stays importable from client components: this
 * one pulls in `lib/seo`, which is server-only. */
import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";
import type { ShopEdit } from "@/lib/shop-edits";

export function editMetadata(
  edit: ShopEdit,
  searchParams: Record<string, string | string[] | undefined>,
): Metadata {
  return pageMetadata({
    title: edit.title,
    description: edit.metaDescription,
    path: `/${edit.slug}`,
    // Passed through for the canonical: a filtered or paged view must not claim to be the
    // page itself, which is how three listings turn into a hundred duplicate URLs.
    searchParams: Object.fromEntries(
      Object.entries(searchParams).map(([k, v]) => [k, Array.isArray(v) ? v[0] : v]),
    ),
  });
}
