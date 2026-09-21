import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApplicationPanel } from "@/components/careers/ApplicationPanel";
import { ApiError } from "@/lib/api";
import { getAdminMeOrNull } from "@/lib/admin-me";
import type { ApplicationDetail } from "@/lib/careers";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Application" };

/**
 * One application in full. `careers.applications.manage`, read-audited at the API.
 *
 * DELETE IS A SEPARATE SCOPE (`careers.applications.delete`, Owner only) and the button
 * is hidden without it — hiding it is ergonomics, not authorization: the endpoint checks
 * the scope inline on every request, so typing the URL gains nothing.
 */
type Params = Promise<{ id: string }>;

export default async function ApplicationPage({ params }: { params: Params }) {
  const { id } = await params;
  const path = `/careers/applications/${id}`;
  await requireAdmin(path);

  const me = await getAdminMeOrNull();
  const canDelete = (me?.scopes ?? []).includes("careers.applications.delete");

  let application: ApplicationDetail;
  try {
    application = await fetchWithAuthOrBounce<ApplicationDetail>(
      `/admin/careers/applications/${id}/`,
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
            ? "Your role does not include reading job applications."
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
    <Link
      href="/careers/applications"
      className="text-sm text-muted hover:text-foreground"
    >
      ← All applications
    </Link>
  );
}
