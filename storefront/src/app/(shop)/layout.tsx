import { cookies, headers } from "next/headers";
import { ACCESS_COOKIE, CART_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { SessionProvider } from "@/components/session/SessionProvider";
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";
import { AnnouncementBar } from "@/components/layout/AnnouncementBar";
import { ScrollShrink } from "@/components/layout/ScrollShrink";
import { CurrencyWelcomeModal } from "@/components/layout/CurrencyWelcomeModal";
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
  // ACCESS **OR** REFRESH, mirroring `hasSession()` in the wishlist BFF route exactly.
  // Access alone would be wrong: it lives 14 minutes, so a shopper twenty minutes into a
  // perfectly good 14-day session would read as anonymous and lose their saved hearts.
  // The same distinction the PDP already draws (product/[slug]/page.tsx: "Gate on the
  // refresh cookie, not access"). This costs no extra work — the jar is already open for
  // the country cookie above.
  const signedIn = Boolean(
    cookieStore.get(ACCESS_COOKIE)?.value || cookieStore.get(REFRESH_COOKIE)?.value,
  );
  // `cart_id` is httpOnly too, so the browser cannot check this for itself — and asking
  // the API whether a cart exists IS the request we are trying to avoid. Presence of the
  // cookie is the only honest "this browser has already been given a cart" signal, and
  // it is exactly what the cart BFF forwards as X-Cart-Id.
  const hasGuestCart = Boolean(cookieStore.get(CART_COOKIE)?.value);

  return (
    // Wraps the Header AND the page, because the wishlist consumers live on both sides of
    // that line: the header heart, and the card hearts inside `children`. A provider in
    // the Header alone would leave every product card still asking.
    <SessionProvider signedIn={signedIn} hasGuestCart={hasGuestCart}>
      <AnnouncementBar items={announcements} />
      <ScrollShrink />
      <CurrencyWelcomeModal currentCountry={currentCountry} geoCountry={geoCountry} />
      <Header />
      <main className="flex-1">{children}</main>
      <Footer />
    </SessionProvider>
  );
}
