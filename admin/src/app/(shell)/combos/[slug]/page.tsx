import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ComboEditor } from "@/components/combo/ComboEditor";
import { ApiError } from "@/lib/api";
import type { ComboDetail } from "@/lib/combos";
import { storefrontUrl } from "@/lib/env";
import type { CountryRef } from "@/lib/reference";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";
import {
  saveComboAction,
  searchProductsAction,
  uploadComboImageAction,
} from "./actions";

export const metadata: Metadata = { title: "Combo" };

type Params = Promise<{ slug: string }>;

/**
 * `/combos/{slug}` — the builder.
 *
 * `fetchWithAuthOrBounce`, never `fetchWithAuth`: this is a Server Component and cannot
 * persist a rotated refresh token, so the writing fetcher would blacklist the old one
 * with nowhere to put the new — a silently ended session.
 *
 * THE PAGE IS NOT THE AUTHORIZATION. `requireAdmin` establishes a session; whether this
 * person may build combos is decided by `HasAdminScope("products.manage")` on every
 * request, from the database. Somebody without it gets a session, a page, and a refusal
 * rendered as a sentence.
 */
export default async function ComboEditorPage({ params }: { params: Params }) {
  const { slug } = await params;
  const path = `/combos/${slug}`;
  await requireAdmin(path);

  let combo: ComboDetail;
  try {
    combo = await fetchWithAuthOrBounce<ComboDetail>(`/admin/combos/${slug}/`, path);
  } catch (e) {
    // `redirect()` works by THROWING, so a bare catch-all here would swallow the renewal
    // bounce and show an error page to somebody whose session was merely stale.
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 404) notFound();
    return (
      <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
        {e.status === 403
          ? "Your role does not include managing products."
          : "This combo could not be loaded."}
      </p>
    );
  }

  const countries = await fetchWithAuthOrBounce<CountryRef[]>("/meta/countries/", path);

  return (
    <ComboEditor
      combo={combo}
      countries={countries.filter((c) => !c.is_rest_of_world)}
      searchProducts={searchProductsAction}
      save={saveComboAction.bind(null, slug)}
      uploadImage={uploadComboImageAction.bind(null, slug)}
      storefrontOrigin={storefrontUrl()}
    />
  );
}
