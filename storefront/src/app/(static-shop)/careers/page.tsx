import type { Metadata } from "next";
import { FadeUp } from "@/components/motion/Motion";
import { RoleBoard } from "@/components/careers/RoleBoard";
import { getJobs, type Job } from "@/lib/careers";
import { pageMetadata } from "@/lib/seo";

/**
 * `/careers` — the careers board. Reached from the header's `More` menu
 * (`lib/site-pages.ts`), which has linked here since 2026-08-16 against a placeholder.
 *
 * ── WHAT THIS REPLACES ──────────────────────────────────────────────────────────────
 *
 * The WordPress page listed fifteen entries — eleven of them "Sales Representative", one
 * per city — each reduced to a title over "Full-Time / Lagos / Good Pay", and told
 * applicants to email careers@. There was no form, no description of any job, and no
 * record of who had applied. Its opening words are kept below, because they are the
 * shop's own voice and they are good; everything under them is new.
 *
 * ── IT STAYS IN `(static-shop)` ─────────────────────────────────────────────────────
 *
 * `getJobs` is a revalidating tagged fetch, not a per-visitor read, so this page
 * prerenders — which is what that layout's rules require. Django flushes the `careers`
 * tag on every posting write (`apps/careers/revalidate.py`), so a role opened in the
 * admin is on this page within a second rather than within the five-minute window.
 *
 * ── THE THREE STATES, AND WHY "EMPTY" IS NOT "BROKEN" ───────────────────────────────
 *
 * `getJobs` answers `null` for an outage and `[]` for "we are genuinely not hiring".
 * They render differently on purpose: one says come back later, the other says the page
 * is having a problem. Collapsing them is how an API outage comes to read as "this
 * company has no jobs".
 */
export const metadata: Metadata = pageMetadata({
  // BARE title. The root layout applies the `%s | Toke Cosmetics` template.
  title: "Careers",
  description:
    "Work at Toke Cosmetics. Open roles in sales, operations, marketing and customer " +
    "care across Lagos, Abuja, Port Harcourt and beyond — apply online in minutes.",
  path: "/careers",
});

export default async function CareersPage() {
  const jobs = await getJobs();
  const failed = jobs === null;
  const open = (jobs ?? []).filter((job) => job.is_accepting);
  const closed = (jobs ?? []).filter((job) => !job.is_accepting);

  return (
    <div className="bg-cream">
      <Hero count={open.length} />
      <Why />

      <section className="wrap py-16 sm:py-20" id="open-roles">
        <FadeUp>
          <div className="max-w-2xl">
            <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-accent">
              Toke positions available
            </p>
            <h2 className="mt-3 font-display text-3xl leading-tight text-foreground sm:text-4xl">
              Begin your career with us
            </h2>
            <p className="mt-4 text-base leading-relaxed text-muted">
              Your growth matters here. Build a meaningful career with a brand that values
              creativity, excellence, and the passion behind every product we create.
            </p>
          </div>
        </FadeUp>

        <div className="mt-12">
          {failed ? (
            <Notice
              title="We could not load our open roles"
              body="Something went wrong at our end, not yours. Refresh in a moment — and if it keeps happening, email careers@tokecosmetics.com and we will send you the list."
            />
          ) : open.length === 0 && closed.length === 0 ? (
            <Notice
              title="No open roles at the moment"
              body="We are not hiring today, but that changes often. Check back, or send your CV to careers@tokecosmetics.com and we will keep it on file."
            />
          ) : (
            <>
              <RoleBoard jobs={open} />
              {closed.length > 0 && <RecentlyClosed jobs={closed} />}
            </>
          )}
        </div>
      </section>

      <GetInTouch />
    </div>
  );
}

function Hero({ count }: { count: number }) {
  return (
    <section className="border-b border-line bg-beige">
      <div className="wrap py-20 sm:py-28">
        <FadeUp>
          <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-accent">
            Careers at Toke Cosmetics
          </p>
          <h1 className="mt-4 max-w-3xl font-display text-4xl leading-[1.1] text-balance text-foreground sm:text-6xl">
            Join our team
          </h1>
          <p className="mt-6 max-w-xl text-base leading-relaxed text-muted sm:text-lg">
            We make skincare people trust, in Nigeria, for the world. If you want work
            that shows — on a shelf, in an inbox, on somebody&apos;s skin — this is a good
            place to do it.
          </p>
          {count > 0 && (
            <a
              href="#open-roles"
              className="mt-9 inline-flex items-center gap-2 rounded-full bg-accent px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
            >
              {count} open {count === 1 ? "role" : "roles"}
              <span aria-hidden>↓</span>
            </a>
          )}
        </FadeUp>
      </div>
    </section>
  );
}

/** Three claims, each one a thing the business actually does rather than a value poster.
 *  Written deliberately narrow: a careers page that promises "passion" and "synergy"
 *  reads as a template, and the candidates worth having notice. */
function Why() {
  const points = [
    {
      title: "You will be trusted early",
      body: "This is a small team running a national brand. Whatever you own, you really own — and the work reaches customers the same week.",
    },
    {
      title: "We train, properly",
      body: "Every member of staff gets a structured training library and time to use it. Nobody is left to work it out from a group chat.",
    },
    {
      title: "Growing, and hiring because of it",
      body: "Our stockists span Lagos, Abuja, Port Harcourt, Onitsha, Benin, Enugu and beyond. Every role on this page exists because the business outgrew doing without it.",
    },
  ];
  return (
    <section className="wrap border-b border-line py-16 sm:py-20">
      <div className="grid gap-10 sm:grid-cols-3 sm:gap-8">
        {points.map((point, index) => (
          <FadeUp key={point.title} delay={index * 0.08}>
            <div>
              <span aria-hidden className="text-sm font-medium tabular-nums tracking-[0.2em] text-accent">
                {String(index + 1).padStart(2, "0")}
              </span>
              <h2 className="mt-3 font-display text-xl text-foreground">{point.title}</h2>
              <p className="mt-2 text-sm leading-relaxed text-muted">{point.body}</p>
            </div>
          </FadeUp>
        ))}
      </div>
    </section>
  );
}

/** Closed roles stay on the page, quietly, below the live ones.
 *
 *  A role that vanishes the moment it is filled makes the candidate who bookmarked it,
 *  or who is halfway through a cover letter, believe the site broke. Told plainly that
 *  it closed, they stop waiting — and they can still read what the job was, which is how
 *  somebody decides whether to watch for the next one. */
function RecentlyClosed({ jobs }: { jobs: Job[] }) {
  return (
    <div className="mt-14 border-t border-line pt-10">
      <h3 className="font-display text-lg text-foreground">Recently closed</h3>
      <p className="mt-1 text-sm text-muted">
        These are no longer taking applications. They are here so you know what we hire for.
      </p>
      <div className="mt-6">
        <RoleBoard jobs={jobs} />
      </div>
    </div>
  );
}

function Notice({ title, body }: { title: string; body: string }) {
  return (
    <FadeUp>
      <div className="rounded-[var(--radius-card)] border border-line bg-surface p-10 text-center sm:p-14">
        <h3 className="font-display text-2xl text-foreground">{title}</h3>
        <p className="mx-auto mt-3 max-w-lg text-sm leading-relaxed text-muted">{body}</p>
      </div>
    </FadeUp>
  );
}

/** The old page's closing block, kept almost verbatim — the address and both inboxes are
 *  the only contact details it published, and people do write to them. */
function GetInTouch() {
  return (
    <section className="border-t border-line bg-beige">
      <div className="wrap py-16 sm:py-20">
        <FadeUp>
          <div className="grid gap-10 sm:grid-cols-2 sm:gap-16">
            <div>
              <h2 className="font-display text-3xl leading-tight text-foreground sm:text-4xl">
                Get in touch with us
              </h2>
              <p className="mt-4 max-w-md text-base leading-relaxed text-muted">
                We&apos;re here to answer your questions, guide your journey, and support you
                every step of the way. Reach out for prompt, thoughtful assistance.
              </p>
            </div>
            <dl className="space-y-8 text-sm">
              <div>
                <dt className="text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
                  Our location
                </dt>
                <dd className="mt-2 text-foreground">
                  3, Aina Close, Efunlawon Estate, Igbe-Laara, Ikorodu, Lagos
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
                  Email
                </dt>
                <dd className="mt-2 space-y-1">
                  <a
                    href="mailto:careers@tokecosmetics.com"
                    className="block text-foreground underline underline-offset-4 hover:text-accent"
                  >
                    careers@tokecosmetics.com
                  </a>
                  <a
                    href="mailto:info@tokecosmetics.com"
                    className="block text-muted underline underline-offset-4 hover:text-accent"
                  >
                    info@tokecosmetics.com
                  </a>
                </dd>
              </div>
            </dl>
          </div>
        </FadeUp>
      </div>
    </section>
  );
}
