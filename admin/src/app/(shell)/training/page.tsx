import type { Metadata } from "next";
import { TrainingLibrary } from "@/components/training/TrainingLibrary";
import { getAdminMeOrNull } from "@/lib/admin-me";
import { ApiError } from "@/lib/api";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";
import type { TrainingRow } from "@/lib/training";

export const metadata: Metadata = { title: "Training" };

const PATH = "/training";

/**
 * `/training` — the staff training library (2026-08-23). Every staff member sees it;
 * only the Owner authors it.
 *
 * WHICH ENDPOINT DEPENDS ON WHO IS ASKING, and admin-me's scopes decide — the same
 * signal the nav filters on, used the same way: ergonomics, not authorization. A
 * `training.manage` holder reads `/admin/training/` (drafts included, because the
 * editor's list must show what staff cannot see yet); everyone else reads
 * `/admin/training-library/` (published only). Both endpoints enforce their own
 * permission from the database on every request — lying to this page about scopes
 * buys a 403, not a draft.
 *
 * `fetchWithAuthOrBounce`, never `fetchWithAuth`: this is a Server Component and
 * cannot persist a rotated refresh token.
 */
export default async function TrainingPage() {
  await requireAdmin(PATH);

  const me = await getAdminMeOrNull();
  const canManage = (me?.scopes ?? []).includes("training.manage");

  let rows: TrainingRow[] = [];
  let error: string | null = null;
  try {
    rows = await fetchWithAuthOrBounce<TrainingRow[]>(
      canManage ? "/admin/training/" : "/admin/training-library/",
      PATH,
    );
  } catch (e) {
    // `redirect()` works by THROWING — a bare catch-all would swallow the renewal
    // bounce and show an error page to somebody whose session was merely stale.
    if (!(e instanceof ApiError)) throw e;
    error = "The training library could not be loaded. Try again in a moment.";
  }

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Training</h1>
      <p className="mt-1 text-sm text-muted">
        {canManage
          ? "The team's video library. Staff see published trainings; hidden ones stay here until you publish them."
          : "How we work, on video. New trainings appear here — check back when something changes."}
      </p>

      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <TrainingLibrary rows={Array.isArray(rows) ? rows : []} canManage={canManage} />
        )}
      </div>
    </div>
  );
}
