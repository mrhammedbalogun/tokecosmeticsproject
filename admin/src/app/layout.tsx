import type { Metadata } from "next";
import "./globals.css";

/**
 * NO WEB FONT, deliberately. The scaffold shipped `next/font/google`, which self-hosts and
 * so is not a runtime third-party request — but it does make every build reach out to
 * Google, and the point of this origin's "zero third parties" rule (see `next.config.ts`)
 * is that there is nothing left to argue about. A system stack costs an internal tool
 * nothing and removes a build-time network dependency.
 *
 * `robots: noindex` here as well as the `X-Robots-Tag` header in `next.config.ts`: the
 * header is the one that binds; the meta tag is what a human sees when they view source
 * and wonder whether this page was meant to be public.
 */
export const metadata: Metadata = {
  title: { default: "Toke Admin", template: "%s · Toke Admin" },
  description: "Toke Cosmetics staff administration.",
  robots: { index: false, follow: false, nocache: true },
};

const SYSTEM_STACK =
  'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full" style={{ fontFamily: SYSTEM_STACK }}>
        {children}
      </body>
    </html>
  );
}
