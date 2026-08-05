import Image from "next/image";
import Link from "next/link";
import { cookies } from "next/headers";
import { getMarkets, COUNTRY_COOKIE, DEFAULT_COUNTRY, normalizeCountry } from "@/lib/country";
import { apiFetch } from "@/lib/api";
import { getAccessToken } from "@/lib/session";
import { CountrySwitcher } from "@/components/layout/CountrySwitcher";
import { CartButton } from "@/components/layout/CartButton";
import { AccountMenu } from "@/components/layout/AccountMenu";
import { MobileNav } from "@/components/layout/MobileNav";
import { SearchBar } from "@/components/layout/SearchBar";
import { CategoryDropdown } from "@/components/layout/CategoryDropdown";

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
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
        <div className="flex items-center gap-3">
          <MobileNav categories={categories} />
          <Link href="/" className="site-logo flex items-center gap-2">
            <Image src="/logos/toke-logo.png" alt="Toke Cosmetics" width={96} height={56} priority />
          </Link>
        </div>
        {/* The approved artifact's menu: Home · All Products · Shop by Category ·
            Skin Quiz · Blog. Categories live in the dropdown, not inline. */}
        <nav className="hidden items-center gap-6 md:flex">
          <Link href="/" className="text-sm hover:text-accent">
            Home
          </Link>
          <Link href="/products" className="text-sm hover:text-accent">
            All Products
          </Link>
          <CategoryDropdown categories={categories.map(({ name, slug }) => ({ name, slug }))} />
          <Link href="/skin-quiz" className="text-sm hover:text-accent">
            Skin Quiz
          </Link>
          <Link href="/blog" className="text-sm hover:text-accent">
            Blog
          </Link>
        </nav>
        <SearchBar />
        <div className="flex items-center gap-5">
          <CountrySwitcher markets={markets} current={country} />
          <AccountMenu signedIn={signedIn} />
          <CartButton />
        </div>
      </div>
    </header>
  );
}
