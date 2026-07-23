import Link from "next/link";
import type { ReactNode } from "react";
import { NewsletterForm } from "@/components/layout/NewsletterForm";

/** Section 15: the large premium footer. Four link columns + a newsletter block,
 * social icons, payment logos and a legal strip. Server Component (no client JS
 * beyond the NewsletterForm island it already embeds). Every policy link still
 * points at the /page/[slug] routes the Plan-12 footer used, so nothing that
 * worked before is lost. */

const COLUMNS: { heading: string; links: readonly (readonly [string, string])[] }[] = [
  {
    heading: "Shop",
    links: [
      ["All products", "/products"],
      ["Face", "/category/face"],
      ["Body", "/category/body"],
      ["Hair", "/category/hair"],
    ],
  },
  {
    heading: "Company",
    links: [
      ["About", "/page/about"],
      ["Blog", "/page/blog"],
      ["Community", "/page/community"],
      ["Wholesale", "/page/wholesale"],
      ["Affiliates", "/page/affiliates"],
    ],
  },
  {
    heading: "Support",
    links: [
      ["Shipping & delivery", "/page/shipping"],
      ["Returns & refunds", "/page/returns"],
      ["Contact us", "/page/contact"],
      ["FAQs", "/page/faqs"],
    ],
  },
  {
    heading: "Legal",
    links: [
      ["Privacy policy", "/page/privacy"],
      ["Terms & conditions", "/page/terms"],
    ],
  },
];

const PAYMENTS = ["visa", "mastercard", "verve", "paystack", "bank-transfer"];

const SOCIALS: { label: string; href: string; icon: ReactNode }[] = [
  {
    label: "Instagram",
    href: "https://www.instagram.com/tokecosmetics",
    icon: (
      <>
        <rect x="3" y="3" width="18" height="18" rx="5" />
        <circle cx="12" cy="12" r="4" />
        <circle cx="17.5" cy="6.5" r="0.5" fill="currentColor" />
      </>
    ),
  },
  {
    label: "Facebook",
    href: "https://www.facebook.com/tokecosmetics",
    icon: <path d="M15 8h2V5h-2a4 4 0 0 0-4 4v2H9v3h2v6h3v-6h2.5l.5-3H14V9a1 1 0 0 1 1-1Z" />,
  },
  {
    label: "TikTok",
    href: "https://www.tiktok.com/@tokecosmetics",
    icon: <path d="M14 4c.4 2.3 1.9 3.8 4 4v3c-1.5 0-2.9-.5-4-1.3V15a5 5 0 1 1-5-5c.3 0 .7 0 1 .1v3.1A2 2 0 1 0 11 15V4h3Z" />,
  },
];

export function Footer() {
  return (
    <footer className="mt-16 border-t border-line bg-surface">
      <div className="mx-auto max-w-7xl px-4 py-14">
        <div className="grid gap-10 md:grid-cols-2 lg:grid-cols-12">
          {/* Brand + newsletter */}
          <div className="lg:col-span-4">
            <h3 className="font-display text-xl">Toke Cosmetics</h3>
            <p className="mt-2 max-w-xs text-sm leading-relaxed text-muted">
              Premium skincare for melanin-rich skin — natural ingredients,
              science-backed, shipped from Nigeria worldwide.
            </p>
            <div className="mt-6">
              <h4 className="text-sm font-medium">Join our list</h4>
              <p className="mt-1 text-sm text-muted">Offers, launches and beauty tips.</p>
              <div className="mt-3 max-w-sm">
                <NewsletterForm />
              </div>
            </div>
            <ul className="mt-6 flex items-center gap-3">
              {SOCIALS.map((s) => (
                <li key={s.label}>
                  <a
                    href={s.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={s.label}
                    className="grid h-9 w-9 place-items-center rounded-full border border-line text-muted transition-colors hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    <svg
                      aria-hidden
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="h-4 w-4"
                    >
                      {s.icon}
                    </svg>
                  </a>
                </li>
              ))}
            </ul>
          </div>

          {/* Link columns */}
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-4 lg:col-span-8">
            {COLUMNS.map((col) => (
              <nav key={col.heading} aria-label={col.heading}>
                <h4 className="text-sm font-semibold">{col.heading}</h4>
                <ul className="mt-3 grid gap-2">
                  {col.links.map(([label, href]) => (
                    <li key={href}>
                      <Link
                        href={href}
                        className="text-sm text-muted transition-colors hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                      >
                        {label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </nav>
            ))}
          </div>
        </div>
      </div>

      <div className="border-t border-line">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 py-5 text-xs text-muted md:flex-row">
          <span>© {new Date().getFullYear()} Toke Cosmetics · Lagos, Nigeria</span>
          <ul className="flex flex-wrap items-center gap-2">
            {PAYMENTS.map((p) => (
              <li key={p} className="rounded border border-line px-2 py-1 capitalize">
                {p.replace("-", " ")}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </footer>
  );
}
