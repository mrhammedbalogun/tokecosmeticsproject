"use client";

/**
 * The roles table, and the panel that edits one.
 *
 * The application count on each row is a NUMBER and never a list: this screen sits
 * behind `careers.manage`, and the applications behind a different scope. It links
 * through to them, which 403s cleanly for somebody who holds only the first.
 */
import { useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { JobForm } from "@/components/careers/JobForm";
import { archiveJob, restoreJob } from "@/app/(shell)/careers/actions";
import type { JobRow } from "@/lib/careers";
import type { CountryRef } from "@/lib/reference";

export function JobTable({
  rows,
  countries,
  canSeeApplications,
}: {
  rows: JobRow[];
  countries: CountryRef[];
  canSeeApplications: boolean;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState<JobRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [pending, startTransition] = useTransition();
  const [message, setMessage] = useState<string | null>(null);

  function run(action: () => Promise<{ message?: string | null }>) {
    startTransition(async () => {
      const result = await action();
      setMessage(result.message ?? null);
      if (!result.message) router.refresh();
    });
  }

  if (creating || editing) {
    return (
      <div className="rounded-[var(--radius-card)] border border-line bg-surface p-5 sm:p-7">
        <h2 className="mb-5 text-base font-semibold">
          {editing ? `Edit ${editing.title}` : "New role"}
        </h2>
        <JobForm
          job={editing}
          countries={countries}
          onDone={() => {
            setEditing(null);
            setCreating(false);
          }}
        />
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm font-medium text-white"
        >
          Post a role
        </button>
        {message && <p className="text-sm text-danger">{message}</p>}
      </div>

      {rows.length === 0 ? (
        <p className="rounded-[var(--radius-card)] border border-line bg-surface p-8 text-center text-sm text-muted">
          No roles here yet. Post one and it appears on tokecosmetics.com/careers as soon
          as you set it to Open.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line bg-surface">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Locations</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Applications</th>
                <th className="px-4 py-3 font-medium sr-only">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-line last:border-0 align-top">
                  <td className="px-4 py-3">
                    <div className="font-medium">{row.title}</div>
                    <div className="mt-0.5 text-xs text-muted">
                      {[row.department, row.employment_type_label, row.compensation_text]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                    {row.status === "open" && (
                      <a
                        href={`${process.env.NEXT_PUBLIC_STOREFRONT_ORIGIN ?? "https://tokecosmetics.com"}/careers/${row.slug}`}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1 inline-block text-xs text-accent underline"
                      >
                        View on the website
                      </a>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted">
                    {row.locations.length === 0
                      ? row.country_name
                      : row.locations.length <= 2
                        ? row.locations.map((l) => l.label).join(", ")
                        : `${row.locations[0].label} +${row.locations.length - 1} more`}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge row={row} />
                  </td>
                  <td className="px-4 py-3">
                    {canSeeApplications ? (
                      <Link
                        href={`/careers/applications?job=${row.id}`}
                        className="text-accent underline"
                      >
                        {row.application_count}
                      </Link>
                    ) : (
                      <span className="text-muted">{row.application_count}</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => setEditing(row)}
                        className="rounded-[var(--radius-card)] border border-line px-3 py-1.5 text-xs hover:border-accent/40"
                      >
                        Edit
                      </button>
                      {row.is_archived ? (
                        <button
                          type="button"
                          disabled={pending}
                          onClick={() => run(() => restoreJob(row.slug))}
                          className="rounded-[var(--radius-card)] border border-line px-3 py-1.5 text-xs hover:border-accent/40 disabled:opacity-50"
                          // Says what it does. A restore that silently republished a
                          // filled job to the public page is a surprise nobody wants.
                          title="Brings it back as a draft, not straight onto the website"
                        >
                          Restore as draft
                        </button>
                      ) : (
                        <button
                          type="button"
                          disabled={pending}
                          onClick={() => {
                            if (
                              confirm(
                                `Archive "${row.title}"? It comes off the careers page. ` +
                                  "The applications it already has are kept.",
                              )
                            ) {
                              run(() => archiveJob(row.slug));
                            }
                          }}
                          className="rounded-[var(--radius-card)] border border-line px-3 py-1.5 text-xs text-danger hover:border-danger/40 disabled:opacity-50"
                        >
                          Archive
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ row }: { row: JobRow }) {
  // `is_accepting` is the SERVER's answer and it folds in the closing date — which is
  // why a role can read "Open" in the status column and still show "closed" here. That
  // difference is the point: it is how somebody notices a deadline passed.
  const [label, tone] = row.is_archived
    ? ["Archived", "text-muted"]
    : row.status === "open" && row.is_accepting
      ? ["Open", "text-ok"]
      : row.status === "open"
        ? ["Past its closing date", "text-warn"]
        : row.status === "closed"
          ? ["Closed", "text-muted"]
          : ["Draft", "text-warn"];
  return <span className={`text-xs font-medium ${tone}`}>{label}</span>;
}
