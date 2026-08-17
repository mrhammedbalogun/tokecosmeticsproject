import type { Metadata } from "next";
import Link from "next/link";
import { pageMetadata } from "@/lib/seo";

/**
 * `/become-a-distributor` — reached from the header's `More` menu (`lib/site-pages.ts`).
 *
 * A CODE ROUTE, NOT a CMS `/page/{slug}` entry, per the 2026-08-16 ruling in
 * `site-pages.ts`: supporting pages with a bespoke layout live in `app/(shop)/`, and the
 * CMS `Page` model keeps the policy text. Adding the nav entry without this file would
 * ship a link to a 404 — `lib/__tests__/site-pages.test.ts` fails if the two disagree.
 *
 * ── WHERE THE COPY CAME FROM ────────────────────────────────────────────────────────
 *
 * Every claim below is carried across from the live WordPress page at
 * `tokecosmetics.com/become-a-distributor/` rather than written fresh. This page makes
 * commercial promises — wholesale pricing, marketing support, a minimum opening order —
 * and inventing a single one of them would be inventing a term of trade.
 *
 * Two deliberate departures from that source:
 *
 * 1. **The stray sentence is dropped.** The WordPress FAQ answer about minimum order
 *    quantity ends with "Yes. Our formulas are designed to work for all skin types…",
 *    which is an answer to a skin-type question that is not being asked. It is a paste
 *    error on the live site, not copy, so it is not reproduced here.
 * 2. **There is no application form.** WordPress collects name, phone, state, country and
 *    address through a form plugin. No equivalent endpoint exists on this platform, and
 *    inventing one would mean a new model, a new admin surface and somewhere for those
 *    submissions to be read — none of which is decided. Until it is, the page routes
 *    applicants to the channels the WordPress page already publishes, which are staffed.
 *    See the punch list in `docs/runbooks/cutover.md`.
 */
export const metadata: Metadata = pageMetadata({
  // BARE title — the root layout applies the `%s | Toke Cosmetics` template.
  title: "Become a Distributor",
  description:
    "Partner with Toke Cosmetics: wholesale pricing, early access to launches, marketing "
    + "support and training for retailers, beauty professionals and entrepreneurs.",
  path: "/become-a-distributor",
});

const BENEFITS: readonly { title: string; body: string }[] = [
  {
    title: "Wholesale pricing",
    body: "Exclusive distributor rates that leave room for a real margin on every line you carry.",
  },
  {
    title: "Early access",
    body: "New formulas reach your shelves before they reach the general catalogue.",
  },
  {
    title: "Discounts and incentives",
    body: "Ongoing trade discounts and incentive programmes as your volume grows.",
  },
  {
    title: "Marketing support",
    body: "Product guides and marketing materials, so you are selling with our words and images rather than improvising your own.",
  },
  {
    title: "Training",
    body: "Help understanding the formulations — what is in them, who they suit, and how to recommend them.",
  },
  {
    title: "A brand that carries",
    body: "The credibility of representing a skincare range customers already ask for by name.",
  },
];

const FAQS: readonly { q: string; a: string }[] = [
  {
    q: "Who can become a Toke Cosmetics distributor?",
    a: "Anyone passionate about skincare and business — established retailers, beauty professionals, or entrepreneurs starting their own venture.",
  },
  {
    q: "What are the benefits of becoming a distributor?",
    a: "Exclusive wholesale prices, early product launches, access to discounts and incentives, marketing support, and the credibility of representing a trusted skincare brand focused on results and customer satisfaction.",
  },
  {
    q: "How do I apply?",
    a: "Send us your details through any of the channels below. Our team reviews every enquiry and comes back to you within a few business days to walk you through the next steps.",
  },
  {
    q: "Is there a minimum order quantity?",
    a: "Yes. There is a minimum opening order to qualify for distributor pricing — it keeps stock available and gives you enough range to launch properly. The figure is shared once your application is approved.",
  },
  {
    q: "Do distributors receive training or marketing materials?",
    a: "Yes. Product guides, marketing materials and ongoing support, so you can explain the formulations accurately and build a customer base that returns.",
  },
];

const WHATSAPP = "https://wa.me/2348130193227";
const EMAIL = "sales@tokecosmetics.com";

export default function BecomeADistributorPage() {
  return (
    <div className="bg-beige">
      <Opening />
      <Benefits />
      <HowItWorks />
      <Faq />
      <Contact />
    </div>
  );
}

function Opening() {
  return (
    <section className="wrap py-20 sm:py-28">
      <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
        Toke Cosmetics trade partnerships
      </p>
      <h1 className="mt-7 max-w-[16ch] text-[3rem] uppercase leading-[0.94] tracking-[0.06em] sm:text-6xl lg:text-7xl">
        Become a
        <br />
        Distributor
      </h1>
      <p className="mt-8 max-w-[58ch] text-base leading-relaxed text-muted sm:text-lg">
        Join our community of skincare enthusiasts and entrepreneurs. Partner with us to bring
        high-quality, results-driven skincare to your customers, and grow your business with a
        brand that truly cares.
      </p>
      <div className="mt-10 flex flex-wrap gap-4">
        <a
          href={WHATSAPP}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-[var(--radius-card)] bg-accent px-7 py-3 text-[12px] font-medium uppercase tracking-[0.16em] text-white transition hover:opacity-90"
        >
          Apply on WhatsApp
        </a>
        <a
          href={`mailto:${EMAIL}?subject=Distributor%20application`}
          className="rounded-[var(--radius-card)] border border-line px-7 py-3 text-[12px] font-medium uppercase tracking-[0.16em] transition hover:text-accent"
        >
          Apply by email
        </a>
      </div>
    </section>
  );
}

function Benefits() {
  return (
    <section className="wrap border-t border-line py-20 sm:py-28">
      <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
        What you get
      </p>
      <h2 className="mt-6 text-3xl uppercase tracking-[0.05em] sm:text-4xl">
        Built for people who sell
      </h2>
      <ul className="mt-14 grid gap-x-12 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
        {BENEFITS.map((b) => (
          <li key={b.title}>
            <h3 className="text-lg">{b.title}</h3>
            <p className="mt-3 text-sm leading-relaxed text-muted">{b.body}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function HowItWorks() {
  const steps = [
    { n: "01", t: "Send your details", d: "Your name, where you trade from, and how to reach you." },
    { n: "02", t: "We review", d: "Our team reads every enquiry and replies within a few business days." },
    { n: "03", t: "Opening order", d: "Once approved, we agree your first order and your distributor pricing." },
  ];
  return (
    <section className="wrap border-t border-line py-20 sm:py-28">
      <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
        How it works
      </p>
      <ol className="mt-12 grid gap-10 sm:grid-cols-3 sm:gap-12">
        {steps.map((s) => (
          <li key={s.n}>
            <span className="text-[11px] font-medium uppercase tracking-[0.22em] text-accent">
              {s.n}
            </span>
            <h3 className="mt-4 text-lg">{s.t}</h3>
            <p className="mt-3 text-sm leading-relaxed text-muted">{s.d}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Faq() {
  return (
    <section className="wrap border-t border-line py-20 sm:py-28">
      <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
        Questions
      </p>
      <h2 className="mt-6 text-3xl uppercase tracking-[0.05em] sm:text-4xl">
        Becoming a distributor
      </h2>
      {/* Plain markup rather than a disclosure widget: five short answers are quicker to
          read open than to click open, and they stay in the page for a crawler. */}
      <dl className="mt-14 max-w-[70ch] space-y-10">
        {FAQS.map((f) => (
          <div key={f.q}>
            <dt className="text-lg">{f.q}</dt>
            <dd className="mt-3 text-sm leading-relaxed text-muted">{f.a}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Contact() {
  return (
    <section className="wrap border-t border-line py-20 sm:py-28">
      <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
        Still have questions?
      </p>
      <h2 className="mt-6 text-3xl uppercase tracking-[0.05em] sm:text-4xl">Talk to us</h2>
      <div className="mt-12 grid gap-10 sm:grid-cols-3">
        <div>
          <h3 className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">Call</h3>
          <p className="mt-4 text-sm leading-relaxed">
            <a href="tel:+2348130193227" className="hover:text-accent">+234 813 019 3227</a>
            <br />
            <a href="tel:+2347035420664" className="hover:text-accent">+234 703 542 0664</a>
          </p>
        </div>
        <div>
          <h3 className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
            WhatsApp
          </h3>
          <p className="mt-4 text-sm leading-relaxed">
            <a href={WHATSAPP} target="_blank" rel="noopener noreferrer" className="hover:text-accent">
              +234 813 019 3227
            </a>
          </p>
        </div>
        <div>
          <h3 className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">Email</h3>
          <p className="mt-4 text-sm leading-relaxed">
            <a href={`mailto:${EMAIL}`} className="hover:text-accent">{EMAIL}</a>
          </p>
        </div>
      </div>
      <p className="mt-14 text-sm text-muted">
        Already buying for yourself rather than to resell?{" "}
        <Link href="/affiliates" className="underline hover:text-accent">
          Our affiliate programme
        </Link>{" "}
        pays commission on what you refer, with no opening order.
      </p>
    </section>
  );
}
