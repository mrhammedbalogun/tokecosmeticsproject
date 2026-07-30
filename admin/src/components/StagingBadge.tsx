import { apiLabel, isProductionApi } from "@/lib/env";

/**
 * A loud red badge whenever this build is NOT talking to the production API.
 *
 * Deliberately fail-loud: an unset or unrecognised `NEXT_PUBLIC_API_URL` shows the badge.
 * Being told "staging" while on production costs a moment's confusion; the reverse costs a
 * production refund made in the belief it was a rehearsal.
 *
 * Nothing renders on production, so the chrome stays quiet where it is meant to be quiet.
 */
export function StagingBadge() {
  if (isProductionApi()) return null;
  return (
    <span
      title={`API: ${apiLabel()}`}
      className="rounded bg-danger px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider text-white"
    >
      Staging · {apiLabel()}
    </span>
  );
}
