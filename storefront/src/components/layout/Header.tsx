import Image from "next/image";
import Link from "next/link";
import { cookies } from "next/headers";
import { getMarkets, COUNTRY_COOKIE, DEFAULT_COUNTRY, normalizeCountry } from "@/lib/country";
import { apiFetch } from "@/lib/api";
import { getAccessToken } from "@/lib/session";
import { CountrySwitcher } from "@/components/layout/CountrySwitcher";
import { CartButton } from "@/components/layout/CartButton";
import { WishlistLink } from "@/components/layout/WishlistLink";
import { AccountMenu } from "@/components/layout/AccountMenu";
import { MobileNav } from "@/components/layout/MobileNav";
import { SearchBar } from "@/components/layout/SearchBar";
import { CategoryDropdown } from "@/components/layout/CategoryDropdown";
import { MoreMenu } from "@/components/layout/MoreMenu";

interface Category { name: string; slug: string; children: Category[] }

export async function Header() {
  const jar = await cookies();
  const markets = await getMarkets().catch(() => []);
  const country = normalizeCountry(
    jar.get(COUNTRY_COOKIE)?.value, markets.map((m) => m.code),
  ) || DEFAULT_COUNTRY;
  const categories = await apiFetch<Category[]>("/categories/", {
    country, next: { revalidate: 3600 },
  }).catch(() => []);
  const signedIn = Boolean(await getAccessToken());

  return (
    <header data-site-header className="sticky top-0 z-40 border-b border-line bg-background/95 backdrop-blur">
      <div className="wrap flex items-center justify-between gap-4 py-3">
        {/* `shrink-0`: without it the brand is the thing flexbox gives up first. The
            country <select> is 198px wide (a native select sizes to its LONGEST option),
            and it squeezed this group — logo included — to 30px on a 390px phone, so no
            logo rendered at all. Measured and screenshotted 2026-08-16. */}
        <div className="flex shrink-0 items-center gap-3">
          <MobileNav categories={categories} markets={markets} country={country} />
          <Link href="/" className="site-logo flex items-center gap-2">
            <Image src="/logos/toke-logo.png" alt="Toke Cosmetics" width={96} height={56} priority />
          </Link>
        </div>
        {/* The approved artifact's menu: Home · All Products · Shop by Category ·
            Skin Quiz · More. Categories live in the dropdown, not inline.
            Blog moved INSIDE `More` on 2026-08-16 — nine supporting pages were due and a
            flat nav of fourteen items is not a nav. See `lib/site-pages.ts`. */}
        <nav className="hidden items-center gap-6 lg:flex">
          <Link href="/" className="text-sm hover:text-accent">
            Home
          </Link>
          <Link href="/products" className="text-sm hover:text-accent">
            All Products
          </Link>
          <CategoryDropdown categories={categories.map(({ name, slug }) => ({ name, slug }))} />
          {/* Top-level rather than inside `More` (2026-09-02): a combo is something to
              BUY, and every other buying route in this bar is top-level. Filing it with
              the policy pages is how it stays unvisited. */}
          <Link href="/combo" className="text-sm hover:text-accent">
            Combos
          </Link>
          <Link href="/skin-quiz" className="text-sm hover:text-accent">
            Skin Quiz
          </Link>
          <MoreMenu />
        </nav>
        <SearchBar />
        {/* `shrink-0` here too, and a tighter gap on small screens: at 390px the old
            gap-5 plus a wrapping "Sign in" pushed the cart button clean off the right
            edge, so a shopper on a phone could not see their basket. */}
        <div className="flex shrink-0 items-center gap-4 sm:gap-5">
          {/* lg and up only — the drawer carries it below that. */}
          <CountrySwitcher
            markets={markets}
            current={country}
            className="hidden items-center gap-1 text-sm lg:flex"
          />
          <AccountMenu signedIn={signedIn} />
          <WishlistLink />
          <CartButton />
        </div>
      </div>
    </header>
  );
}
