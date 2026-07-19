import Link from "next/link";
import { NewsletterForm } from "@/components/layout/NewsletterForm";

const POLICIES = [
  ["Contact us", "/page/contact"],
  ["Shipping & delivery", "/page/shipping"],
  ["Returns & refunds", "/page/returns"],
  ["Privacy policy", "/page/privacy"],
  ["Terms & conditions", "/page/terms"],
] as const;

const PAYMENTS = ["visa", "mastercard", "verve", "paystack", "bank-transfer"];

export function Footer() {
  return (
    <footer className="mt-16 border-t border-line bg-surface">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-12 md:grid-cols-3">
        <div>
          <h3 className="font-display text-lg">Toke Cosmetics</h3>
          <p className="mt-2 text-sm text-muted">Premium beauty, shipped worldwide.</p>
        </div>
        <nav aria-label="Footer" className="grid gap-2">
          {POLICIES.map(([label, href]) => (
            <Link key={href} href={href} className="text-sm text-muted hover:text-accent">{label}</Link>
          ))}
        </nav>
        <div>
          <h4 className="text-sm font-medium">Join our list</h4>
          <p className="mt-1 text-sm text-muted">Offers, launches and beauty tips.</p>
          <div className="mt-3"><NewsletterForm /></div>
        </div>
      </div>
      <div className="border-t border-line">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 py-5 text-xs text-muted md:flex-row">
          <span>© {new Date().getFullYear()} Toke Cosmetics. All rights reserved.</span>
          <ul className="flex items-center gap-3">
            {PAYMENTS.map((p) => (
              <li key={p} className="rounded border border-line px-2 py-1 capitalize">{p.replace("-", " ")}</li>
            ))}
          </ul>
        </div>
      </div>
    </footer>
  );
}
