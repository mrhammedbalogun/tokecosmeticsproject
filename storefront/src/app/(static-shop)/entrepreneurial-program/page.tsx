import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { FadeUp } from "@/components/motion/Motion";
import { ApplyForm } from "@/components/programme/ApplyForm";
import { JsonLd } from "@/components/seo/JsonLd";
import { getProgrammeConfig } from "@/lib/entrepreneurship";
import { faqJsonLd, pageMetadata } from "@/lib/seo";

/**
 * `/entrepreneurial-program` — the Student Entrepreneurship Program.
 *
 * Reached from the header's `More` menu (`lib/site-pages.ts`), which has linked here
 * against a `PagePlaceholder` since 2026-08-16.
 *
 * ── WHAT THIS REPLACES, AND THE ONE THING THE OLD PAGE NEVER SAID ───────────────────
 *
 * The retired WordPress page (old.tokecosmetics.com/entrepreneur) had a headline, one
 * paragraph, a six-field form and five FAQs. Its own words are kept below where they are
 * good — they are the shop's voice — but it never explained the actual offer: that Toke
 * gives an approved student products UP FRONT AND FREE, and the student pays for them
 * out of what they sell. That is the whole proposition and it was missing from the page
 * asking people to sign up for it. Everything in "How it works" exists to say it plainly.
 *
 * ── IT STAYS IN `(static-shop)` ─────────────────────────────────────────────────────
 *
 * `getProgrammeConfig` is a revalidating tagged fetch, not a per-visitor read, so this
 * page prerenders — which is what that layout's rules require. Django flushes the
 * `entrepreneurship` tag whenever the intake switch is saved, so closing applications
 * takes the form off this page within a second rather than within the cache window.
 *
 * NOTHING HERE MAY BECOME A DYNAMIC READ. `headers()` or a cookie would silently drop
 * the page out of static rendering, exactly as the currency popup would have — see the
 * layout's docstring.
 *
 * ── THE BANNER HAS ITS HEADLINE BAKED IN, WHICH DECIDES THE HERO ────────────────────
 *
 * The supplied artwork is 1839x855 with "Student Entrepreneurship Program", a tagline
 * and a "Join the Program" button drawn INTO the image. At ~390px — which is most of
 * this shop's traffic — all of that renders unreadably small, and none of the button is
 * clickable at any size. So:
 *
 *   * the image is cropped responsively to its photographic half on phones
 *     (`aspect-[5/4] object-[68%]`) and shown whole from `sm:` up;
 *   * the real <h1> is VISIBLE on phones and `sm:sr-only` above, where the artwork
 *     already carries it — a real heading either way, for search engines and screen
 *     readers;
 *   * `alt=""`. The image is decorative ONCE a real heading exists, and alt text
 *     repeating the headline would have a screen reader announce it twice in a row;
 *   * EARN / LEARN / GROW and a working "Apply now" button are rendered as HTML under
 *     the banner, because on a phone they are cropped out of the artwork entirely and
 *     they are the only call to action it has.
 */
export const metadata: Metadata = pageMetadata({
  // BARE title. The root layout applies the `%s | Toke Cosmetics` template, so repeating
  // the brand here would render it twice.
  title: "Student Entrepreneurship Program",
  description:
    "Start a skincare business while you study. Toke Cosmetics gives approved students " +
    "products up front at no cost — you sell, you pay from what you make, you keep the " +
    "rest. Training and marketing support included. Apply online.",
  path: "/entrepreneurial-program",
  image: "/programme/student-programme-hero.webp",
});

const HERO = "/programme/student-programme-hero.webp";

/** The five questions from the WordPress page, answered again — three of them rewritten,
 *  because the originals never mentioned the free stock, and one added (the money
 *  question everybody actually has). Kept in one array so the rendered accordion and the
 *  `FAQPage` structured data cannot drift apart. */
const FAQS: { q: string; a: string }[] = [
  {
    q: "What is the Toke Cosmetics Student Entrepreneurship Program?",
    a:
      "It is a way to run a real skincare business while you study. We give you Toke " +
      "Cosmetics products to sell, you sell them to people around you, and you pay us " +
      "for the stock out of what you collect. You build sales experience, a customer " +
      "base and an income — with our products, our training and our name behind you.",
  },
  {
    q: "Do I need money to start?",
    a:
      "No. That is the point of the programme. Approved students receive their first " +
      "stock at no cost up front — you pay for it after you have sold it. There is no " +
      "joining fee, no registration fee and no deposit, and anyone asking you for one " +
      "is not us.",
  },
  {
    q: "Who can join the programme?",
    a:
      "Any student at a university, polytechnic or college who is serious about " +
      "skincare, selling and their own growth. No prior sales experience is needed — " +
      "we train you. What we look for is somebody reachable, honest about what they " +
      "can sell, and already talking to people we would want as customers.",
  },
  {
    q: "How do I earn?",
    a:
      "You earn on every product you sell, and there are referral bonuses and " +
      "performance incentives on top as you grow. We agree the exact terms with you " +
      "before you receive any stock, so you know what you keep before you sell " +
      "anything.",
  },
  {
    q: "Will I get training and support?",
    a:
      "Yes. Every student on the programme gets brand and product training, marketing " +
      "material you can post as-is, and a person on our team you can actually reach. " +
      "You are not handed a box and left to work it out.",
  },
  {
    q: "How do I apply?",
    a:
      "Fill in the form on this page. We read every application ourselves, and if you " +
      "look like a good fit someone will contact you on the number you give us to talk " +
      "it through and take you from there.",
  },
];

export default async function EntrepreneurialProgramPage() {
  const config = await getProgrammeConfig();

  return (
    <div className="bg-cream">
      <JsonLd data={faqJsonLd(FAQS)} />

      <Hero />
      <Proposition />
      <HowItWorks />
      <WhatYouGet />
      <WhoCanJoin />
      <Faq />
      <Apply config={config} />
      <GetInTouch />
    </div>
  );
}

function Hero() {
  return (
    <section className="border-b border-line bg-beige">
      <div className="relative">
        <Image
          src={HERO}
          // DECORATIVE, deliberately: the <h1> below carries the same words as real
          // text. An alt repeating them would be announced twice in a row.
          alt=""
          width={1839}
          height={855}
          // `loading="eager"` + `fetchPriority="high"`, NOT `priority`. This is the LCP
          // element, so it must not be lazy — but `priority` is DEPRECATED as of
          // Next.js 16 (`node_modules/next/dist/docs/01-app/03-api-reference/02-components/image.md`),
          // which names these two as the replacement. The rest of this repo still says
          // `priority` because it predates the deprecation; do not "fix" this back.
          loading="eager"
          fetchPriority="high"
          sizes="100vw"
          className="aspect-[5/4] w-full object-cover object-[68%_center] sm:aspect-[1839/855] sm:object-center"
        />
      </div>

      <div className="wrap py-10 sm:py-12">
        {/* VISIBLE ON PHONES, hidden above — where the artwork carries it. A real
            heading in both cases, which is what the crop takes away and what search
            engines and screen readers need regardless. */}
        <h1 className="font-display text-3xl leading-[1.12] text-balance text-foreground sm:sr-only">
          Student Entrepreneurship Program
        </h1>
        <p className="mt-3 max-w-xl text-base leading-relaxed text-muted sm:sr-only">
          Turn your passion for skincare into real opportunities.
        </p>

        {/* EARN / LEARN / GROW — in the artwork on desktop, cropped out on a phone, and
            never clickable in either. Rendered as HTML so they exist at every width. */}
        <ul className="mt-6 flex flex-wrap items-center gap-x-3 gap-y-2 sm:mt-0">
          {["Earn", "Learn", "Grow"].map((word) => (
            <li
              key={word}
              className="rounded-full border border-accent/25 bg-accent/5 px-4 py-1.5 text-xs font-medium uppercase tracking-[0.16em] text-accent"
            >
              {word}
            </li>
          ))}
        </ul>

        <div className="mt-7 flex flex-wrap items-center gap-3">
          {/* The artwork's "Join the Program" button is a drawing. This is the one that
              works, and it is above the fold on a phone. */}
          <a
            href="#apply"
            className="inline-flex items-center gap-2 rounded-full bg-accent px-7 py-3 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
          >
            Apply now
            <span aria-hidden>→</span>
          </a>
          <a
            href="#how-it-works"
            className="inline-flex items-center rounded-full border border-line bg-surface px-6 py-3 text-sm font-medium text-foreground transition-colors hover:border-accent/40"
          >
            How it works
          </a>
        </div>
      </div>
    </section>
  );
}

/** The offer, said once, in the plainest words available.
 *
 *  This band exists because the old page did not have it. "We equip you with products,
 *  mentorship and marketing tools" is true and tells a student nothing about whether they
 *  can afford to start — which is the only question standing between them and the form. */
function Proposition() {
  return (
    <section className="wrap border-b border-line py-16 sm:py-20">
      <FadeUp>
        <div className="max-w-3xl">
          <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-accent">
            Start with nothing but your phone
          </p>
          <h2 className="mt-3 font-display text-3xl leading-tight text-foreground sm:text-4xl">
            We give you the products. You pay us after you sell them.
          </h2>
          <p className="mt-5 text-base leading-relaxed text-muted">
            Most student businesses die before they start, because starting one needs
            money a student does not have. This one does not. Get approved and your first
            stock arrives at no cost to you — sell it to friends, classmates, family and
            everyone who asks what you use, pay us for the stock out of what you collect,
            and keep what is left.
          </p>
          <p className="mt-4 text-base leading-relaxed text-muted">
            You are selling skincare people already buy, under a name they already trust,
            with training and marketing material we give you. What you bring is the
            effort.
          </p>
        </div>
      </FadeUp>
    </section>
  );
}

function HowItWorks() {
  const steps = [
    {
      title: "Apply",
      body: "Fill in the form on this page. It takes about two minutes and needs nothing but your school details and a number we can reach you on.",
    },
    {
      title: "Talk it through",
      body: "If you look like a good fit, someone from our team calls you. You will hear exactly what you earn, what you owe on the stock and when — before you agree to anything.",
    },
    {
      title: "Get trained, get your stock",
      body: "You get brand and product training and marketing material you can post as-is. Then your first products arrive — free, up front, nothing to pay on the day.",
    },
    {
      title: "Sell, settle, keep the rest",
      body: "You sell. You pay us for the stock out of what you collect, and the rest is yours. Sell it all and you can take more — that is how this grows.",
    },
  ];
  return (
    <section id="how-it-works" className="scroll-mt-24 border-b border-line bg-beige">
      <div className="wrap py-16 sm:py-20">
        <FadeUp>
          <div className="max-w-2xl">
            <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-accent">
              How it works
            </p>
            <h2 className="mt-3 font-display text-3xl leading-tight text-foreground sm:text-4xl">
              Four steps, and none of them cost you anything
            </h2>
          </div>
        </FadeUp>

        <ol className="mt-12 grid gap-8 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
          {steps.map((step, index) => (
            <FadeUp key={step.title} delay={index * 0.08}>
              <li className="relative h-full rounded-[var(--radius-card)] border border-line bg-surface p-6">
                <span
                  aria-hidden
                  className="text-sm font-medium tabular-nums tracking-[0.2em] text-accent"
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <h3 className="mt-3 font-display text-xl text-foreground">
                  {step.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{step.body}</p>
              </li>
            </FadeUp>
          ))}
        </ol>
      </div>
    </section>
  );
}

function WhatYouGet() {
  const items = [
    {
      title: "Products up front, free",
      body: "Your starting stock costs you nothing on the day it arrives. You pay for it from what you sell.",
    },
    {
      title: "Training that is actually run",
      body: "Brand and product training, the same library our own staff use, and time set aside to go through it.",
    },
    {
      title: "Marketing you can post today",
      body: "Photos, captions and product information made for you — so your first post does not have to wait on your design skills.",
    },
    {
      title: "Referral and performance bonuses",
      body: "Earn on what you sell, and earn again for the people you bring in behind you.",
    },
    {
      title: "A real person on our side",
      body: "Someone on our team you can reach when a customer asks something you cannot answer.",
    },
    {
      title: "Experience that outlives it",
      body: "Selling, stock, margins, customers and follow-up. It is a business, and it will read as one long after you graduate.",
    },
  ];
  return (
    <section className="wrap border-b border-line py-16 sm:py-20">
      <FadeUp>
        <div className="max-w-2xl">
          <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-accent">
            What you get
          </p>
          <h2 className="mt-3 font-display text-3xl leading-tight text-foreground sm:text-4xl">
            Everything except the excuse
          </h2>
        </div>
      </FadeUp>
      <div className="mt-12 grid gap-8 sm:grid-cols-2 lg:grid-cols-3 lg:gap-10">
        {items.map((item, index) => (
          <FadeUp key={item.title} delay={index * 0.05}>
            <div>
              <div className="flex items-start gap-3">
                <Tick />
                <h3 className="font-display text-lg leading-snug text-foreground">
                  {item.title}
                </h3>
              </div>
              <p className="mt-2 pl-8 text-sm leading-relaxed text-muted">{item.body}</p>
            </div>
          </FadeUp>
        ))}
      </div>
    </section>
  );
}

function WhoCanJoin() {
  return (
    <section className="border-b border-line bg-beige">
      <div className="wrap py-16 sm:py-20">
        <div className="grid gap-10 lg:grid-cols-2 lg:gap-16">
          <FadeUp>
            <div>
              <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-accent">
                Who can join
              </p>
              <h2 className="mt-3 font-display text-3xl leading-tight text-foreground sm:text-4xl">
                Students. That is genuinely the only requirement.
              </h2>
              <p className="mt-5 text-base leading-relaxed text-muted">
                The programme is open to students at any university, polytechnic or
                college in Nigeria, the United Kingdom, the United States and Canada. No
                sales experience, no business background and no capital — we would rather
                train somebody willing than inherit somebody certain.
              </p>
            </div>
          </FadeUp>
          <FadeUp delay={0.08}>
            <div className="rounded-[var(--radius-card)] border border-line bg-surface p-6 sm:p-8">
              <h3 className="font-display text-lg text-foreground">
                What we look for
              </h3>
              <ul className="mt-4 space-y-3 text-sm leading-relaxed text-muted">
                {[
                  "You are reachable. A working number you answer is worth more here than a perfect CV.",
                  "You are honest about what you can sell. We would rather start you small and grow than write off stock.",
                  "You already talk to people — a hostel, a class, a group chat, a following. Any audience counts.",
                  "You will follow up. Most of this business is answering the second message.",
                ].map((line) => (
                  <li key={line} className="flex gap-3">
                    <Tick />
                    <span>{line}</span>
                  </li>
                ))}
              </ul>
            </div>
          </FadeUp>
        </div>
      </div>
    </section>
  );
}

/** `<details>`, not a React accordion — the same ruling the FAQ page states: the
 *  behaviour is the browser's, it works before hydration and without JavaScript, the
 *  keyboard and screen-reader handling is the platform's, and Ctrl+F finds text inside a
 *  closed answer. A hand-rolled accordion would ship client JS to do worse. */
function Faq() {
  return (
    <section className="wrap border-b border-line py-16 sm:py-20">
      <FadeUp>
        <div className="max-w-2xl">
          <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-accent">
            FAQ
          </p>
          <h2 className="mt-3 font-display text-3xl leading-tight text-foreground sm:text-4xl">
            The questions we actually get
          </h2>
        </div>
      </FadeUp>
      <div className="mt-10 max-w-3xl divide-y divide-line border-y border-line">
        {FAQS.map((item) => (
          <details key={item.q} className="group">
            <summary className="flex cursor-pointer list-none items-start justify-between gap-4 py-5 text-left text-sm font-medium marker:content-none hover:text-accent">
              {item.q}
              {/* Rotates to a minus when open. `aria-hidden` because the open/closed
                  state is already announced by <details> itself. */}
              <svg
                aria-hidden
                viewBox="0 0 14 14"
                className="mt-1 h-3.5 w-3.5 shrink-0 text-muted transition-transform group-open:rotate-45"
              >
                <path d="M7 1v12M1 7h12" fill="none" stroke="currentColor" strokeWidth="1.5" />
              </svg>
            </summary>
            <p className="pb-5 text-sm leading-relaxed text-muted">{item.a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}

function Apply({
  config,
}: {
  config: Awaited<ReturnType<typeof getProgrammeConfig>>;
}) {
  return (
    <section id="apply" className="scroll-mt-24 border-b border-line bg-beige">
      <div className="wrap py-16 sm:py-20">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] lg:gap-16">
          <FadeUp>
            <div className="lg:sticky lg:top-28">
              <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-accent">
                Apply
              </p>
              <h2 className="mt-3 font-display text-3xl leading-tight text-foreground sm:text-4xl">
                Students today, brighter tomorrows
              </h2>
              <p className="mt-5 text-base leading-relaxed text-muted">
                Take the first step toward building your own skincare business with Toke
                Cosmetics. Two minutes, no fee, and nothing to pay if you are accepted.
              </p>
              <p className="mt-4 text-sm leading-relaxed text-muted">
                Already applied? There is no need to send it twice — if you need to
                correct something, just fill the form in again with the right details.
              </p>
            </div>
          </FadeUp>

          <FadeUp delay={0.08}>
            <div className="rounded-[var(--radius-card)] border border-line bg-cream p-6 sm:p-8">
              {config.is_open ? (
                <ApplyForm config={config} />
              ) : (
                // Not an error state: applications being closed is a decision, and the
                // page reads as one rather than as something broken.
                <div className="py-6 text-center">
                  <h3 className="font-display text-2xl text-foreground">
                    Applications are closed for now
                  </h3>
                  <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted">
                    {config.closed_message}
                  </p>
                  <Link
                    href="/products"
                    className="mt-6 inline-block text-sm font-medium text-accent underline underline-offset-4"
                  >
                    See what you would be selling
                  </Link>
                </div>
              )}
            </div>
          </FadeUp>
        </div>
      </div>
    </section>
  );
}

/** The old page's closing block, kept almost verbatim — these four contact points are
 *  the only ones it published, and people do use them. */
function GetInTouch() {
  return (
    <section className="bg-cream">
      <div className="wrap py-16 sm:py-20">
        <FadeUp>
          <div className="grid gap-10 sm:grid-cols-2 sm:gap-16">
            <div>
              <h2 className="font-display text-3xl leading-tight text-foreground sm:text-4xl">
                Still have questions?
              </h2>
              <p className="mt-4 max-w-md text-base leading-relaxed text-muted">
                Ask before you apply, if you would rather. We are happy to talk it through
                first — call, text or email, whichever suits you.
              </p>
            </div>
            <dl className="space-y-8 text-sm">
              <div>
                <dt className="text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
                  Call or text
                </dt>
                <dd className="mt-2 space-y-1">
                  {["+2348130193227", "+2347035420664"].map((number) => (
                    <a
                      key={number}
                      href={`tel:${number}`}
                      className="block text-foreground underline underline-offset-4 hover:text-accent"
                    >
                      {number}
                    </a>
                  ))}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
                  Email
                </dt>
                <dd className="mt-2 space-y-1">
                  {["info@tokecosmetics.com", "help@tokecosmetics.com"].map((address) => (
                    <a
                      key={address}
                      href={`mailto:${address}`}
                      className="block text-foreground underline underline-offset-4 hover:text-accent"
                    >
                      {address}
                    </a>
                  ))}
                </dd>
              </div>
            </dl>
          </div>
        </FadeUp>
      </div>
    </section>
  );
}

function Tick() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 20 20"
      className="mt-0.5 h-5 w-5 shrink-0 text-accent"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <circle cx="10" cy="10" r="8.5" className="opacity-25" />
      <path d="m6.2 10.4 2.6 2.6 5-5.4" />
    </svg>
  );
}
