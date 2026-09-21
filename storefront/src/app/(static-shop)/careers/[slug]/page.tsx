import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApplyForm } from "@/components/careers/ApplyForm";
import { FadeUp } from "@/components/motion/Motion";
import { JsonLd } from "@/components/seo/JsonLd";
import { getJob, getJobs, locationSummary, type Job } from "@/lib/careers";
import { breadcrumbJsonLd, jobPostingJsonLd, pageMetadata, stripHtml } from "@/lib/seo";

/**
 * `/careers/[slug]` — one role, and the form to apply for it.
 *
 * ── WHY EACH ROLE HAS ITS OWN PAGE RATHER THAN AN EXPANDING CARD ────────────────────
 *
 * Google Jobs. `JobPosting` structured data must sit on a page whose canonical URL IS
 * the job, so an accordion on `/careers` would make all five roles ineligible. It is
 * also the URL somebody pastes into a WhatsApp group, which is how a sales role in
 * Onitsha actually reaches somebody in Onitsha.
 *
 * ── PRERENDERED, WITH THE FORM AS THE ONLY LIVE PART ────────────────────────────────
 *
 * `generateStaticParams` builds every open role at deploy time and `dynamicParams` (the
 * default) covers one opened afterwards; the `careers` tag flushes both when a posting
 * changes. The apply form is a client island that talks to Django directly — see
 * `lib/careers.ts` for why it bypasses our own server.
 *
 * ── AN UNKNOWN SLUG MUST 404, AND THAT IS NOT FREE HERE ─────────────────────────────
 *
 * `getJob` answers `null` for both "no such role" and "the API is down", and this page
 * calls `notFound()` on it. A soft 200 shell would be worse — a shell turns a missing
 * page into an indexable empty one — but it does mean a backend outage renders as 404
 * on a role that exists. That is the right trade for a page Google indexes: a wrong 404
 * is re-crawled, a wrong 200 is remembered.
 */
type Params = Promise<{ slug: string }>;

export async function generateStaticParams() {
  const jobs = await getJobs();
  return (jobs ?? []).map((job) => ({ slug: job.slug }));
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug } = await params;
  const job = await getJob(slug);
  if (!job) {
    // `noindex`, because this metadata is produced for a slug the board does not carry —
    // either a removed role or an API outage. The page itself 404s; this only governs
    // what a crawler that arrived mid-outage is told.
    return pageMetadata({
      title: "Role not found",
      description: "This role is no longer listed. See our open roles at Toke Cosmetics.",
      path: `/careers/${slug}`,
      noindex: true,
    });
  }

  return pageMetadata({
    // BARE title; the root layout appends the brand.
    title: `${job.title} — ${locationSummary(job)}`,
    description:
      job.summary ||
      stripHtml(job.description).slice(0, 180) ||
      `${job.title} at Toke Cosmetics, ${locationSummary(job)}.`,
    path: `/careers/${job.slug}`,
  });
}

export default async function RolePage({ params }: { params: Params }) {
  const { slug } = await params;
  const job = await getJob(slug);
  if (!job) notFound();

  return (
    <div className="bg-cream">
      <JsonLd data={jobPostingJsonLd(job, `/careers/${job.slug}`)} />
      <JsonLd
        data={breadcrumbJsonLd([
          { name: "Careers", path: "/careers" },
          { name: job.title, path: `/careers/${job.slug}` },
        ])}
      />

      <section className="border-b border-line bg-beige">
        <div className="wrap py-14 sm:py-20">
          <FadeUp>
            <Link
              href="/careers"
              className="inline-flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-accent"
            >
              <span aria-hidden>←</span> All open roles
            </Link>
            {job.department && (
              <p className="mt-8 text-[11px] font-medium uppercase tracking-[0.22em] text-accent">
                {job.department}
              </p>
            )}
            <h1 className="mt-3 max-w-3xl font-display text-4xl leading-[1.1] text-balance text-foreground sm:text-5xl">
              {job.title}
            </h1>

            <ul className="mt-6 flex flex-wrap gap-2 text-sm">
              <Badge>{job.employment_type_label}</Badge>
              <Badge>{job.workplace_type_label}</Badge>
              {job.compensation_text && <Badge>{job.compensation_text}</Badge>}
              {!job.is_accepting && <Badge tone="muted">Applications closed</Badge>}
            </ul>

            {job.locations.length > 0 && (
              <div className="mt-6">
                <h2 className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted">
                  {job.locations.length === 1 ? "Location" : "Hiring in"}
                </h2>
                {/* Every city listed, not a summary. On the board the same role is one
                    card reading "Alimosho and 10 other locations"; here is where a
                    reader finds out whether theirs is on it. */}
                <ul className="mt-2 flex flex-wrap gap-2">
                  {job.locations.map((location) => (
                    <li
                      key={location.id}
                      className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-foreground"
                    >
                      {location.label}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {job.closes_at && job.is_accepting && (
              <p className="mt-6 text-sm text-muted">
                Applications close{" "}
                <time dateTime={job.closes_at} className="text-foreground">
                  {new Date(job.closes_at).toLocaleDateString("en-NG", {
                    day: "numeric",
                    month: "long",
                    year: "numeric",
                  })}
                </time>
                .
              </p>
            )}
          </FadeUp>
        </div>
      </section>

      <div className="wrap grid gap-12 py-14 sm:py-20 lg:grid-cols-[minmax(0,1fr)_minmax(360px,420px)] lg:gap-16">
        <div className="min-w-0">
          {job.summary && (
            <p className="font-display text-xl leading-relaxed text-foreground sm:text-2xl">
              {job.summary}
            </p>
          )}
          {job.description && (
            <div
              className="rich-text mt-8 text-base leading-relaxed text-muted [&_h3]:mt-8 [&_h3]:font-display [&_h3]:text-xl [&_h3]:text-foreground [&_strong]:text-foreground"
              // Sanitised on write by nh3 (`apps/cms/sanitize.py`), exactly like the CMS
              // pages this markup shares its stylesheet with.
              dangerouslySetInnerHTML={{ __html: job.description }}
            />
          )}
          {job.requirements && (
            <div className="mt-10">
              <h2 className="font-display text-2xl text-foreground">What we are looking for</h2>
              <div
                className="rich-text mt-4 text-base leading-relaxed text-muted [&_strong]:text-foreground"
                dangerouslySetInnerHTML={{ __html: job.requirements }}
              />
            </div>
          )}
        </div>

        <aside className="lg:sticky lg:top-24 lg:self-start">
          <div className="rounded-[var(--radius-card)] border border-line bg-surface p-6 sm:p-8">
            {job.is_accepting ? (
              <>
                <h2 className="font-display text-2xl text-foreground">Apply for this role</h2>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  It takes a couple of minutes. You will need your CV to hand.
                </p>
                <div className="mt-6">
                  <ApplyForm job={job} />
                </div>
              </>
            ) : (
              <ClosedPanel job={job} />
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

function ClosedPanel({ job }: { job: Job }) {
  return (
    <div className="text-center">
      <h2 className="font-display text-2xl text-foreground">This role has closed</h2>
      <p className="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-muted">
        We are no longer taking applications for {job.title}. The description is still
        here so you know what we hire for — and roles like it come round again.
      </p>
      <Link
        href="/careers"
        className="mt-6 inline-flex items-center gap-2 rounded-full bg-accent px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
      >
        See what is open now
      </Link>
      <p className="mt-4 text-xs text-muted">
        Or send your CV to{" "}
        <a href="mailto:careers@tokecosmetics.com" className="underline underline-offset-2">
          careers@tokecosmetics.com
        </a>{" "}
        and we will keep it on file.
      </p>
    </div>
  );
}

function Badge({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: "default" | "muted";
}) {
  return (
    <li
      className={[
        "rounded-full border px-3 py-1.5",
        tone === "muted"
          ? "border-line bg-beige text-muted"
          : "border-accent/25 bg-accent/5 text-accent",
      ].join(" ")}
    >
      {children}
    </li>
  );
}
