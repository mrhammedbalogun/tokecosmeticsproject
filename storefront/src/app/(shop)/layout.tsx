import { cookies, headers } from "next/headers";
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";
import { CountrySuggestionBanner } from "@/components/layout/CountrySuggestionBanner";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

export default async function ShopLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const currentCountry = cookieStore.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  // Geo hint forwarded by proxy.ts as a request header (empty locally). The banner reads
  // it once from this meta tag; the server never forces a market on the user.
  const geo = (await headers()).get("x-geo-country") ?? "";

  return (
    <>
      <meta name="x-geo-country" content={geo} />
      <CountrySuggestionBanner currentCountry={currentCountry} />
      <Header />
      <main className="flex-1">{children}</main>
      <Footer />
    </>
  );
}
