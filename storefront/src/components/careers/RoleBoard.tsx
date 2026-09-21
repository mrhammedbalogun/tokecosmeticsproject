"use client";

/**
 * The list of open roles, with the location filter above it.
 *
 * ── WHY THERE IS A FILTER AT ALL FOR FIVE CARDS ─────────────────────────────────────
 *
 * Because the roles are not evenly spread: one of them (Sales Representative) is hiring
 * in eleven cities and the rest are Lagos-only. A reader in Enugu is looking for exactly
 * one thing on this page, and without the filter they have to open a card to find out
 * whether it is for them. Picking a city answers that before they click.
 *
 * FILTERING IS CLIENT-SIDE, unlike the store locator's. The whole board is five objects
 * that arrived in the prerendered HTML; a round trip to narrow five cards would be
 * slower and would cost the page its static rendering for nothing.
 *
 * ── THE FILTER IS NOT IN THE URL ────────────────────────────────────────────────────
 *
 * Deliberately, and this is the one place this page differs from `/find-stores`, which
 * puts its whole selection in the URL. That page exists to be shared filtered ("here is
 * the shop in Alimosho"); this one is shared as a whole ("we are hiring"), and the thing
 * worth linking to is a ROLE, which already has its own URL. A querystring here would
 * add a shareable state nobody wants and a `useSearchParams` boundary that would make
 * the page dynamic.
 */
import { useMemo, useState } from "react";
import Link from "next/link";
import { FadeUp } from "@/components/motion/Motion";
import { allLocations, locationSummary, type Job } from "@/lib/careers";

const ALL = "__all__";

export function RoleBoard({ jobs }: { jobs: Job[] }) {
  const [place, setPlace] = useState<string>(ALL);
  const locations = useMemo(() => allLocations(jobs), [jobs]);

  const shown = useMemo(() => {
    if (place === ALL) return jobs;
    return jobs.filter((job) => job.locations.some((l) => l.label === place));
  }, [jobs, place]);

  return (
    <div>
      {/* One row of chips rather than a <select>: there are rarely more than a dozen
          cities, they are the page's primary navigation, and a select hides every option
          until it is opened. The horizontal scroll is what keeps that true on a phone —
          and `-mx-*`/`px-*` is what stops the first and last chip being clipped by it. */}
      {locations.length > 1 && (
        <div className="mb-10 -mx-5 overflow-x-auto px-5 pb-2 sm:mx-0 sm:px-0">
          <div
            role="group"
            aria-label="Filter roles by location"
            className="flex w-max gap-2 sm:w-auto sm:flex-wrap"
          >
            <Chip active={place === ALL} onClick={() => setPlace(ALL)}>
              All locations
            </Chip>
            {locations.map((label) => (
              <Chip key={label} active={place === label} onClick={() => setPlace(label)}>
                {label}
              </Chip>
            ))}
          </div>
        </div>
      )}

      <p aria-live="polite" className="sr-only">
        {shown.length} {shown.length === 1 ? "role" : "roles"} shown
      </p>

      {shown.length === 0 ? (
        <div className="rounded-[var(--radius-card)] border border-line bg-surface p-10 text-center">
          <p className="font-display text-xl text-foreground">
            Nothing open in {place} right now
          </p>
          <p className="mx-auto mt-2 max-w-md text-sm text-muted">
            We are still hiring elsewhere, and new roles go up here as they open.
          </p>
          <button
            type="button"
            onClick={() => setPlace(ALL)}
            className="mt-5 text-sm font-medium text-accent underline underline-offset-4"
          >
            See every open role
          </button>
        </div>
      ) : (
        <ul className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((job, index) => (
            <li key={job.slug}>
              <FadeUp delay={Math.min(index, 5) * 0.05}>
                <RoleCard job={job} />
              </FadeUp>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={[
        "shrink-0 rounded-full border px-4 py-2 text-sm transition-colors",
        active
          ? "border-accent bg-accent text-white"
          : "border-line bg-surface text-muted hover:border-accent/40 hover:text-foreground",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

/**
 * One role.
 *
 * THE WHOLE CARD IS THE LINK, via a stretched overlay rather than by wrapping everything
 * in an `<a>`: a link containing a heading and three badges reads as one enormous run-on
 * link to a screen reader, and the accessible name becomes the entire card's text. This
 * way the link's name is the role title and the rest is ordinary content.
 */
function RoleCard({ job }: { job: Job }) {
  const closed = !job.is_accepting;
  return (
    <article className="group relative flex h-full flex-col rounded-[var(--radius-card)] border border-line bg-surface p-6 transition-all duration-300 hover:-translate-y-0.5 hover:border-accent/30 hover:shadow-lg motion-reduce:transform-none motion-reduce:transition-none sm:p-7">
      <div className="flex items-start justify-between gap-3">
        {job.department ? (
          <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted">
            {job.department}
          </span>
        ) : (
          <span />
        )}
        {closed && (
          <span className="shrink-0 rounded-full border border-line bg-beige px-2.5 py-1 text-[11px] font-medium uppercase tracking-wider text-muted">
            Closed
          </span>
        )}
      </div>

      <h3 className="mt-3 font-display text-xl leading-snug text-balance text-foreground sm:text-2xl">
        <Link
          href={`/careers/${job.slug}`}
          className="after:absolute after:inset-0 after:content-[''] focus:outline-none focus-visible:underline focus-visible:underline-offset-4"
        >
          {job.title}
        </Link>
      </h3>

      {job.summary && (
        <p className="mt-3 text-sm leading-relaxed text-muted">{job.summary}</p>
      )}

      <dl className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted">
        <div className="flex items-center gap-1.5">
          <dt className="sr-only">Location</dt>
          <PinIcon />
          <dd className="text-foreground">{locationSummary(job)}</dd>
        </div>
        <div className="flex items-center gap-1.5">
          <dt className="sr-only">Employment type</dt>
          <ClockIcon />
          <dd>{job.employment_type_label}</dd>
        </div>
        {job.compensation_text && (
          <div className="flex items-center gap-1.5">
            <dt className="sr-only">Pay</dt>
            <TagIcon />
            <dd>{job.compensation_text}</dd>
          </div>
        )}
      </dl>

      <span className="mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-accent">
        {closed ? "Read the role" : "View and apply"}
        <span
          aria-hidden
          className="transition-transform duration-300 group-hover:translate-x-1 motion-reduce:transform-none"
        >
          →
        </span>
      </span>
    </article>
  );
}

const iconClass = "h-3.5 w-3.5 shrink-0 text-muted";

function PinIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={iconClass} aria-hidden>
      <path d="M12 21s7-5.2 7-11a7 7 0 1 0-14 0c0 5.8 7 11 7 11Z" />
      <circle cx="12" cy="10" r="2.5" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={iconClass} aria-hidden>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  );
}

function TagIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={iconClass} aria-hidden>
      <path d="M20.6 13.4 12 22l-9-9V4h9l8.6 8.6a1.4 1.4 0 0 1 0 2Z" />
      <circle cx="7.5" cy="7.5" r="1.3" fill="currentColor" stroke="none" />
    </svg>
  );
}
