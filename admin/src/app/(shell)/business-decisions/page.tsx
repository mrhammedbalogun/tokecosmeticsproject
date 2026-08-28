import type { Metadata } from "next";
import { BusinessDecisions } from "@/components/config/BusinessDecisions";
import { ApiError } from "@/lib/api";
import type { BusinessDecisionsRow } from "@/lib/business-decisions";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Business Decisions" };

const PATH = "/business-decisions";

export default async function BusinessDecisionsPage() {
  await requireAdmin(PATH);

  let decisions: BusinessDecisionsRow | null = null;
  let error: string | null = null;
  try {
    decisions = await fetchWithAuthOrBounce<BusinessDecisionsRow>(
      "/admin/business-decisions/",
      PATH,
    );
  } catch (e) {
    // requireAdmin's redirect works by throwing, so anything that is not an ApiError has
    // to keep travelling.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include changing business decisions."
        : "The business decisions could not be loaded.";
  }

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Business Decisions</h1>
      <p className="mt-1 text-sm text-muted">
        The commercial numbers behind the referral programme. Changes apply to new orders
        immediately — commission already earned and orders already placed keep the rates
        they were given.
      </p>

      <div className="mt-6">
        {error || !decisions ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error ?? "The business decisions could not be loaded."}
          </p>
        ) : (
          <BusinessDecisions decisions={decisions} />
        )}
      </div>
    </div>
  );
}
