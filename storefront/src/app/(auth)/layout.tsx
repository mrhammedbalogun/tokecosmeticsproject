import Image from "next/image";
import Link from "next/link";

/**
 * Auth pages sit outside the shop layout, so they get no header or footer. That is right
 * for focus — but it left a visitor bounced here from a gated page with no way back to the
 * store and no branding to confirm where they are. This is the minimum that fixes both:
 * the logo, linked home. Deliberately not the full header (no cart, no search, no nav) —
 * the point of a separate auth surface is that there is nothing else to click.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col px-4 py-10">
      <Link href="/" className="mb-10 self-center" aria-label="Toke Cosmetics — back to the store">
        <Image src="/logos/toke-logo.png" alt="Toke Cosmetics" width={96} height={56} priority />
      </Link>
      <main className="flex flex-1 flex-col">{children}</main>
    </div>
  );
}
