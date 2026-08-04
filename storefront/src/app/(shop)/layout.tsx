import { cookies, headers } from "next/headers";
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";
import { AnnouncementBar } from "@/components/layout/AnnouncementBar";
import { ScrollShrink } from "@/components/layout/ScrollShrink";
import { CountrySuggestionBanner } from "@/components/layout/CountrySuggestionBanner";
import { announcementsFrom, getHomepage } from "@/lib/cms";
import { ANNOUNCEMENTS } from "@/lib/home-content";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { GEO_COUNTRY_HEADER } from "@/lib/geo";

export default async function ShopLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const currentCountry = cookieStore.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  // Geo hint forwarded by proxy.ts as a request header (empty locally). Passed as a prop; the
  // banner still consumes it inside useEffect so SSR and first-paint output stay identical.
  const geoCountry = (await headers()).get(GEO_COUNTRY_HEADER) ?? "";
  // Announcement strips are CMS-managed (Plan-19c) and country-targeted, so the fetch is
  // country-keyed. A null payload — empty CMS, or the API down — falls back to the
  // Plan-13 fixtures rather than emptying a bar that renders on every page.
  const homepage = await getHomepage(currentCountry);
  const announcements = announcementsFrom(homepage, ANNOUNCEMENTS);

  return (
    <>
      <AnnouncementBar items={announcements} />
      <ScrollShrink />
      <CountrySuggestionBanner currentCountry={currentCountry} geoCountry={geoCountry} />
      <Header />
      <main className="flex-1">{children}</main>
      <Footer />
    </>
  );
}
