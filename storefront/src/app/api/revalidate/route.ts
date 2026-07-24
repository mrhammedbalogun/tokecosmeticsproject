import { revalidateTag } from "next/cache";

/** On-demand data-cache invalidation (Plan-13 D7 — the storefront half). Django's
 * post_save webhook will call this in production (deferred to Plan-22); until then
 * it can be driven manually. Tags: "catalog" (lists/tree/brands), "product:<slug>".
 * timingSafeEqual is overkill for a long random secret; simple compare is fine.
 *
 * Next 16 note: revalidateTag's single-arg form is deprecated (bundled docs —
 * revalidateTag.md); we pass the "max" profile for stale-while-revalidate, which the
 * docs recommend precisely for product catalogs (serve stale, refresh in background). */
export async function POST(req: Request) {
  const secret = process.env.REVALIDATE_SECRET;
  const given = req.headers.get("x-revalidate-secret");
  if (!secret || given !== secret) {
    return Response.json({ detail: "Invalid secret." }, { status: 401 });
  }
  const body = await req.json().catch(() => ({}));
  const tags: unknown = body?.tags;
  if (!Array.isArray(tags) || tags.length === 0 || !tags.every((t) => typeof t === "string")) {
    return Response.json({ detail: "tags must be a non-empty string array." }, { status: 400 });
  }
  for (const tag of tags as string[]) revalidateTag(tag, "max");
  return Response.json({ revalidated: tags });
}
