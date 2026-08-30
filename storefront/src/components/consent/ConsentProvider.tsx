"use client";
/**
 * Consent state for the whole storefront (Plan-44).
 *
 * Everything that loads a tracking script or sends an event asks this context first.
 * Nothing else in the app reads the consent cookie directly — one reader means one place
 * where the regional rule is applied, and the regional rule is the part with legal
 * consequences if it drifts.
 *
 * ── WHY THIS IS A CLIENT COMPONENT THAT READS ITS OWN COOKIES ───────────────────────
 *
 * The obvious design is a Server Component reading `cookies()` and passing the answer
 * down. It was rejected: `cookies()` opts the route out of static rendering, and this
 * provider sits in the root layout, so that one call would make EVERY page in the shop
 * dynamic — the product pages, the category pages, the CMS pages, all of which live on
 * ISR today.
 *
 * ── WHY `useSyncExternalStore` AND NOT AN EFFECT ────────────────────────────────────
 *
 * `document.cookie` is an external store, and this is the hook for reading one. The
 * first version of this file read it in a `useEffect` and called `setState`, which
 * `react-hooks` flags — correctly, it causes a cascading render on every page load, and
 * it is the pattern the rule's own documentation points at.
 *
 * Two stores are subscribed:
 *
 *   `mounted`  false on the server, true on the client. This is what keeps the server
 *              render and the hydration render identical (both produce no banner and no
 *              pixel) while still letting the browser act on the real cookie a beat
 *              later. Reading the cookie in a lazy `useState` initialiser instead would
 *              disagree between the two renders and produce a hydration mismatch.
 *   `cookies`  a STRING snapshot of the two cookies that matter. A string because
 *              `useSyncExternalStore` compares snapshots by identity, so returning a
 *              freshly-built object every call would re-render for ever.
 *
 * Cookies emit no change event, so the store is notified explicitly by our own writes —
 * which is the only thing that changes them within a page's life.
 *
 * The cost of all this is a first paint with no banner. That is the standard behaviour
 * of every consent banner on the web, and it is safe because the pixels are gated on the
 * same state: nothing loads during that window either.
 */
import { createContext, useCallback, useContext, useMemo, useState, useSyncExternalStore } from "react";
import {
  CLICK_ID_COOKIE,
  CLICK_ID_MAX_AGE,
  CONSENT_COOKIE,
  CONSENT_MAX_AGE,
  type ConsentState,
  DENIED,
  clickIdsFromUrl,
  decodeConsent,
  defaultConsent,
} from "@/lib/consent";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import type { MarketingConfig } from "@/lib/marketing";

interface ConsentContextValue {
  consent: ConsentState;
  /** The store-wide master switch. False means there is nothing to consent to, so the
   * banner and the "Cookie choices" link both render nothing. */
  trackingEnabled: boolean;
  /** True once the cookie has been read. Until then nothing may load: rendering a pixel
   * against the pre-hydration default would fire it for a visitor who declined. */
  ready: boolean;
  showBanner: boolean;
  accept: () => void;
  reject: () => void;
  save: (choice: { analytics: boolean; marketing: boolean }) => void;
  /** Re-open the banner — the footer's "Cookie choices" link. Withdrawal has to be as
   * easy as granting, which is the requirement, not a design preference. */
  reopen: () => void;
}

const ConsentContext = createContext<ConsentContextValue>({
  consent: DENIED,
  trackingEnabled: false,
  ready: false,
  showBanner: false,
  accept: () => {},
  reject: () => {},
  save: () => {},
  reopen: () => {},
});

export function useConsent(): ConsentContextValue {
  return useContext(ConsentContext);
}

// --- the cookie store ---------------------------------------------------------------

const listeners = new Set<() => void>();

function subscribeToCookies(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notifyCookieChange(): void {
  listeners.forEach((listener) => listener());
}

function readCookie(name: string): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? match[1] : "";
}

/** A string, so the snapshot is stable by value. See the module docstring. */
function cookieSnapshot(): string {
  return `${readCookie(CONSENT_COOKIE)}|${readCookie(COUNTRY_COOKIE)}`;
}

function serverCookieSnapshot(): string {
  return "|";
}

const noopSubscribe = () => () => {};

function writeCookie(name: string, value: string, maxAge: number): void {
  const secure = window.location.protocol === "https:" ? "; secure" : "";
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAge}; samesite=lax${secure}`;
}

function deleteCookie(name: string): void {
  document.cookie = `${name}=; path=/; max-age=0; samesite=lax`;
}

/**
 * Cookies the vendors' own scripts set, cleared when marketing consent is withdrawn.
 *
 * Best-effort, and honest about it: these are first-party cookies on our own domain, so
 * we can delete them, but a vendor script still loaded in the page will write them
 * again. That is why withdrawal ALSO reloads (see `TrackingScripts`) — deleting the
 * cookies is the tidy-up, not the control.
 */
const VENDOR_COOKIES = ["_fbp", "_fbc", "_ttp", "_scid", "_scid_r", "_ga", "_gcl_au"];

export function ConsentProvider({
  config,
  children,
}: {
  config: MarketingConfig;
  children: React.ReactNode;
}) {
  /**
   * Is there anything to consent TO?
   *
   * The master switch is not the only way to be measuring nothing: a shop with tracking
   * enabled and no channel configured loads no pixel (`TrackingScripts` needs an id) and
   * sends no server event (`events.enqueue_purchase` iterates zero rows). Showing a
   * banner then is pure friction on a checkout funnel — and worse, it NAMES Facebook,
   * Instagram, TikTok, Snapchat and Google to a customer whose data none of them is
   * receiving, which is not a true statement to put in front of someone.
   *
   * This is exactly the reasoning the master switch already carries, applied to the
   * other way of ending up at zero. Caught the day Plan-44 first reached production
   * with every channel still dark.
   */
  const measuring = config.tracking_enabled && config.channels.length > 0;

  const mounted = useSyncExternalStore(noopSubscribe, () => true, () => false);
  const cookies = useSyncExternalStore(subscribeToCookies, cookieSnapshot, serverCookieSnapshot);
  // null = "no explicit decision about the banner yet"; the derived default applies.
  const [bannerOverride, setBannerOverride] = useState<boolean | null>(null);

  const [storedConsent, country] = useMemo(() => {
    const [rawConsent, rawCountry] = cookies.split("|");
    return [
      decodeConsent(rawConsent, config.consent_version),
      (rawCountry || DEFAULT_COUNTRY).toUpperCase(),
    ] as const;
  }, [cookies, config.consent_version]);

  const consent = useMemo<ConsentState>(() => {
    if (!mounted || !measuring) return DENIED;
    return (
      storedConsent
      ?? defaultConsent(country, config.consent_required_countries, config.consent_version)
    );
  }, [mounted, measuring, config, storedConsent, country]);

  /**
   * The click ids on THIS landing, read straight out of the URL.
   *
   * The proxy could not store them — a visitor with no consent cookie is exactly the
   * case it refuses to write for — so they are recovered here and persisted if and when
   * consent is granted. Derived at render rather than held in state: the URL is not
   * going to change under us, and a state copy would be one more thing to keep in step.
   */
  const pendingClickIds = useMemo(() => {
    if (!mounted) return {};
    return clickIdsFromUrl(new URLSearchParams(window.location.search));
  }, [mounted]);

  const choose = useCallback(
    (analytics: boolean, marketing: boolean) => {
      writeCookie(CONSENT_COOKIE, JSON.stringify({
        v: config.consent_version, a: analytics ? 1 : 0, m: marketing ? 1 : 0,
      }), CONSENT_MAX_AGE);

      if (marketing) {
        if (Object.keys(pendingClickIds).length > 0) {
          writeCookie(CLICK_ID_COOKIE, JSON.stringify(pendingClickIds), CLICK_ID_MAX_AGE);
        }
      } else {
        deleteCookie(CLICK_ID_COOKIE);
        VENDOR_COOKIES.forEach(deleteCookie);
      }

      setBannerOverride(false);
      notifyCookieChange();
    },
    [config.consent_version, pendingClickIds],
  );

  const ready = mounted;
  const showBanner =
    bannerOverride
    ?? (mounted && measuring && storedConsent === null);

  const value = useMemo<ConsentContextValue>(
    () => ({
      consent,
      trackingEnabled: measuring,
      ready,
      showBanner,
      accept: () => choose(true, true),
      reject: () => choose(false, false),
      save: ({ analytics, marketing }) => choose(analytics, marketing),
      reopen: () => setBannerOverride(true),
    }),
    [consent, measuring, ready, showBanner, choose],
  );

  return <ConsentContext.Provider value={value}>{children}</ConsentContext.Provider>;
}
