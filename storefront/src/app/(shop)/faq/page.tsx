import type { Metadata } from "next";
import Link from "next/link";
import { getFaq } from "@/lib/faq";
import { JsonLd } from "@/components/seo/JsonLd";
import { pageMetadata } from "@/lib/seo";

/**
 * `/faq` — the questions customers actually ask, grouped.
 *
 * ── A CODE ROUTE, NOT A CMS PAGE, AND THE CONTENT IS STILL EDITABLE ─────────────────
 *
 * `lib/site-pages.ts` explains the rule: pages in the More menu are code routes because
 * they need bespoke layouts a sanitised HTML blob cannot express. An FAQ is the clearest
 * case of that — it is an accordion, it carries `FAQPage` structured data, and it is
 * added to one question at a time. The LAYOUT lives here; every word on the page comes
 * from `cms.FaqCategory` / `cms.FaqItem` and is edited in the admin.
 *
 * ── `<details>`, NOT A REACT ACCORDION ──────────────────────────────────────────────
 *
 * The open/close behaviour is the browser's. That buys real things on a page like this:
 * it works before hydration and without JavaScript, the keyboard and screen-reader
 * behaviour is the platform's rather than something we have to get right ourselves, and
 * Ctrl+F finds text inside a closed answer in Chrome. A hand-rolled accordion would ship
 * client JS to do worse.
 */
export const metadata: Metadata = pageMetadata({
  title: "Frequently Asked Questions",
  description:
    "Answers about delivery, payment, returns and our products — and how to reach us if "
    + "your question is not here.",
  path: "/faq",
});

export default async function FaqPage() {
  const categories = await getFaq();
  const questions = categories.flatMap((c) => c.items);

  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:py-16">
      {/* Google reads this to show the questions directly in search results. Built from
          the same rows the page renders, so the two can never disagree. Only emitted
          when there is something to describe. */}
      {questions.length > 0 && (
        <JsonLd
          data={{
            "@context": "https://schema.org",
            "@type": "FAQPage",
            mainEntity: questions.map((item) => ({
              "@type": "Question",
              name: item.question,
              acceptedAnswer: { "@type": "Answer", text: item.answer },
            })),
          }}
        />
      )}

      <header className="border-b border-line pb-8">
        <h1 className="font-display text-3xl leading-tight sm:text-4xl">
          Frequently asked questions
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-muted">
          Delivery, payment, returns and the products themselves. If your question is not
          here, <Link href="/contact-us" className="text-accent underline underline-offset-2">
            talk to us
          </Link>{" "}
          — we answer every message.
        </p>
      </header>

      {categories.length === 0 ? (
        <p className="mt-10 text-sm text-muted">
          Our answers are being updated. In the meantime,{" "}
          <Link href="/contact-us" className="text-accent underline underline-offset-2">
            contact us
          </Link>{" "}
          and we will help you directly.
        </p>
      ) : (
        categories.map((category) => (
          <section key={category.slug} id={category.slug} className="mt-12 scroll-mt-24">
            <h2 className="font-display text-2xl">{category.name}</h2>
            {category.blurb && (
              <p className="mt-1 text-sm text-muted">{category.blurb}</p>
            )}
            <div className="mt-5 divide-y divide-line border-y border-line">
              {category.items.map((item) => (
                <details key={item.id} className="group">
                  <summary
                    className="flex cursor-pointer list-none items-start justify-between gap-4 py-4 text-left text-sm font-medium marker:content-none hover:text-accent"
                  >
                    {item.question}
                    {/* Rotates to a minus when open. `aria-hidden` because the
                        open/closed state is already announced by <details> itself. */}
                    <svg
                      aria-hidden
                      viewBox="0 0 14 14"
                      className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted transition-transform group-open:rotate-45"
                    >
                      <path d="M7 1v12M1 7h12" fill="none" stroke="currentColor" strokeWidth="1.5" />
                    </svg>
                  </summary>
                  {/* The one place an editor's markup reaches a customer. Sanitised
                      server-side on write (`cms/sanitize.py`), never here. */}
                  <div
                    className="cms-prose pb-5 text-sm"
                    dangerouslySetInnerHTML={{ __html: item.answer }}
                  />
                </details>
              ))}
            </div>
          </section>
        ))
      )}

      <p className="mt-12 border-t border-line pt-8 text-sm text-muted">
        Still stuck?{" "}
        <Link href="/contact-us" className="text-accent underline underline-offset-2">
          Contact us
        </Link>{" "}
        or{" "}
        <Link href="/find-stores" className="text-accent underline underline-offset-2">
          visit one of our stores
        </Link>
        .
      </p>
    </div>
  );
}
