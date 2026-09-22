import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApplicationPanel } from "@/components/entrepreneurship/ApplicationPanel";
import { ApiError } from "@/lib/api";
import { getAdminMeOrNull } from "@/lib/admin-me";
import type { ApplicationDetail } from "@/lib/entrepreneurship";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Programme application" };

/**
 * One application in full. `entrepreneurship.applications.manage`, read-audited at the
 * API — this route is the link in the staff alert email, so it is the first thing
 * somebody opens after being told a student applied.
 *
 * DELETE IS A SEPARATE SCOPE (`entrepreneurship.applications.delete`, Owner only) and
 * the button is hidden without it — hiding it is ergonomics, not authorization: the
 * endpoint checks the scope inline on every request, so typing the URL gains nothing.
 *
 * `/entrepreneurship/notifications` is a SIBLING static segment and wins over this
 * dynamic one in the App Router's matching order, which is what keeps the two from
 * colliding. Application ids are integers, so no real row can ever be shadowed by it.
 */
type Params = Promise<{ id: string }>;

export default async function ProgrammeApplicationPage({
  params,
}: {
  params: Params;
}) {
  const { id } = await params;
  const path = `/entrepreneurship/${id}`;
  await requireAdmin(path);

  const me = await getAdminMeOrNull();
  const canDelete = (me?.scopes ?? []).includes(
    "entrepreneurship.applications.delete",
  );

  let application: ApplicationDetail;
  try {
    application = await fetchWithAuthOrBounce<ApplicationDetail>(
      `/admin/entrepreneurship/applications/${id}/`,
      path,
    );
  } catch (e) {
    // `redirect()` throws, so a bare catch-all would swallow the session-renewal bounce.
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 404) notFound();
    return (
      <div>
        <BackLink />
        <p className="mt-6 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
          {e.status === 403
            ? "Your role does not include reading programme applications."
            : "This application could not be loaded."}
        </p>
      </div>
    );
  }

  return (
    <div>
      <BackLink />
      <div className="mt-6">
        <ApplicationPanel application={application} canDelete={canDelete} />
      </div>
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/entrepreneurship" className="text-sm text-muted hover:text-foreground">
      ← All applications
    </Link>
  );
}
