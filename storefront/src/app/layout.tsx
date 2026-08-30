import type { Metadata } from "next";
import { Playfair_Display, Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";
import { ConsentBanner } from "@/components/consent/ConsentBanner";
import { ConsentProvider } from "@/components/consent/ConsentProvider";
import { TrackingScripts } from "@/components/consent/TrackingScripts";
import { getMarketingConfig } from "@/lib/marketing";

const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  display: "swap",
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: { default: "Toke Cosmetics", template: "%s | Toke Cosmetics" },
  description: "Premium beauty and cosmetics — shop skincare, makeup and more.",
};

/**
 * `async` since Plan-44, for `getMarketingConfig()` — which is a REVALIDATING fetch, not
 * a dynamic read. That distinction is the whole reason the tracking configuration is
 * served by an API rather than read from cookies here: `cookies()` or `headers()` in the
 * root layout would opt every page in the shop out of static rendering, and the shop is a
 * catalogue that lives on ISR. A cached fetch costs nothing per request.
 *
 * The consent state itself is read in the browser (`ConsentProvider`), for the same
 * reason.
 */
export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const marketing = await getMarketingConfig();

  return (
    <html lang="en" className={`${playfair.variable} ${inter.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <ConsentProvider config={marketing}>
          <Providers>{children}</Providers>
          {/* Both AFTER the page: the banner is a bar rather than a modal (consent must
              be freely given, so the shop stays readable), and no pixel may load before
              the consent cookie has been read — see TrackingScripts. */}
          <TrackingScripts config={marketing} />
          <ConsentBanner />
        </ConsentProvider>
      </body>
    </html>
  );
}
