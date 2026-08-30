"use client";
/**
 * The pixel loaders, gated on consent (Plan-44).
 *
 * ── NOTHING LOADS UNTIL THE COOKIE HAS BEEN READ ────────────────────────────────────
 *
 * `ready` is the gate, and it is not a nicety. The provider's pre-hydration state is
 * DENIED, so rendering these on the server and letting them hydrate would inject the
 * scripts for one paint before the consent cookie was even read — i.e. for a visitor who
 * had declined. Everything below therefore renders only after the effect has run.
 *
 * ── WHY NOT `strategy="beforeInteractive"` FOR THE GOOGLE CONSENT DEFAULT ────────────
 *
 * Because it could not work. `next/script`'s own reference (node_modules/next/dist/docs/
 * 01-app/03-api-reference/02-components/script.md) is explicit: a `beforeInteractive`
 * script is "injected into the initial HTML from the server". This component renders
 * NOTHING on the server — that is the whole point of the `ready` gate above — so a
 * `beforeInteractive` script here would simply never be emitted.
 *
 * What actually makes the ordering safe is `dataLayer`. It is a plain array, and gtag.js
 * drains it IN ORDER whenever it finishes loading. So an inline script that pushes the
 * consent default executes immediately, while the external gtag.js is still downloading,
 * and the default is therefore in the queue before anything can read it. Placement in the
 * array is the contract, not script load order.
 *
 * ── GOOGLE IS TOLD ABOUT A REFUSAL; THE OTHER THREE ARE NOT LOADED ──────────────────
 *
 * This is **Advanced Consent Mode**, and it is a decision rather than the only option.
 *
 * Google's two supported shapes are: ADVANCED (load gtag.js always, signal the refusal,
 * and Google receives a cookieless ping it uses for conversion modelling) and BASIC (do
 * not load gtag.js at all until consent, and lose the modelling). Advanced is what
 * Google recommends and what most shops run; Basic is the strictly more conservative
 * reading, because a refusing visitor still causes a request to Google.
 *
 * Advanced was chosen because the shop is Nigeria-first — where the regime is opt-out
 * and gtag loads with consent granted anyway — so the choice only bites for a GB/EEA
 * visitor who actively refuses, and Basic would cost conversion modelling on every
 * market to change that one case.
 *
 * **Reversing it is one line**: gate the `anyGoogle` block below on
 * `(consent.marketing || consent.analytics)` and Google is treated exactly like the
 * other three. Hammed's call if a DPA view hardens.
 *
 * The three ad pixels have no equivalent signal, so for them a refusal always means the
 * script is never injected at all.
 */
import { useEffect, useRef } from "react";
import Script from "next/script";
import { useConsent } from "@/components/consent/ConsentProvider";
import type { MarketingConfig } from "@/lib/marketing";

function pixelId(config: MarketingConfig, code: string): string {
  return config.channels.find((c) => c.code === code)?.pixel_id ?? "";
}

function googleConsentPayload(marketing: boolean, analytics: boolean): string {
  return `{'ad_storage':'${marketing ? "granted" : "denied"}',`
    + `'ad_user_data':'${marketing ? "granted" : "denied"}',`
    + `'ad_personalization':'${marketing ? "granted" : "denied"}',`
    + `'analytics_storage':'${analytics ? "granted" : "denied"}'}`;
}

export function TrackingScripts({ config }: { config: MarketingConfig }) {
  const { consent, ready, trackingEnabled } = useConsent();
  const hadMarketingScripts = useRef(false);

  const meta = pixelId(config, "meta");
  const tiktok = pixelId(config, "tiktok");
  const snapchat = pixelId(config, "snapchat");
  const googleAds = pixelId(config, "google_ads");
  const ga4 = pixelId(config, "ga4");
  const anyGoogle = googleAds || ga4;

  /**
   * WITHDRAWAL MID-SESSION.
   *
   * Google is simply told (`consent update`, below). The other three cannot be told
   * anything: once `fbevents.js` is in the page it stays there, and React unmounting a
   * `<Script>` does not unload it. Deleting their cookies — which the provider does — is
   * a tidy-up, not a control, because the loaded script would write them again.
   *
   * So a withdrawal that follows a grant reloads the page. It is blunt, and it is the
   * only thing that actually honours the refusal in the session it was made in. The
   * guard means it fires only in that one direction: a visitor who arrives having
   * already declined never had the scripts, and never sees a reload.
   */
  useEffect(() => {
    if (!ready || !trackingEnabled) return;
    if (consent.marketing) {
      hadMarketingScripts.current = true;
      return;
    }
    if (hadMarketingScripts.current) {
      hadMarketingScripts.current = false;
      window.location.reload();
    }
  }, [consent.marketing, ready, trackingEnabled]);

  /** Google's own withdrawal path, which needs no reload. */
  useEffect(() => {
    if (!ready || !anyGoogle || typeof window.gtag !== "function") return;
    window.gtag("consent", "update", {
      ad_storage: consent.marketing ? "granted" : "denied",
      ad_user_data: consent.marketing ? "granted" : "denied",
      ad_personalization: consent.marketing ? "granted" : "denied",
      analytics_storage: consent.analytics ? "granted" : "denied",
    });
  }, [consent.marketing, consent.analytics, ready, anyGoogle]);

  if (!ready || !trackingEnabled) return null;

  return (
    <>
      {consent.marketing && meta && (
        <Script id="meta-pixel" strategy="afterInteractive">
          {`!function(f,b,e,v,n,t,s)
{if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};
if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];
s.parentNode.insertBefore(t,s)}(window,document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init','${meta}');fbq('track','PageView');`}
        </Script>
      )}

      {consent.marketing && tiktok && (
        <Script id="tiktok-pixel" strategy="afterInteractive">
          {`!function(w,d,t){w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];
ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie"];
ttq.setAndDefer=function(t,e){t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};
for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);
ttq.instance=function(t){for(var e=ttq._i[t]||[],n=0;n<ttq.methods.length;n++)ttq.setAndDefer(e,ttq.methods[n]);return e};
ttq.load=function(e,n){var r="https://analytics.tiktok.com/i18n/pixel/events.js";
ttq._i=ttq._i||{};ttq._i[e]=[];ttq._i[e]._u=r;ttq._t=ttq._t||{};ttq._t[e]=+new Date;
ttq._o=ttq._o||{};ttq._o[e]=n||{};var o=document.createElement("script");
o.type="text/javascript";o.async=!0;o.src=r+"?sdkid="+e+"&lib="+t;
var a=document.getElementsByTagName("script")[0];a.parentNode.insertBefore(o,a)};
ttq.load('${tiktok}');ttq.page();}(window,document,'ttq');`}
        </Script>
      )}

      {consent.marketing && snapchat && (
        <Script id="snap-pixel" strategy="afterInteractive">
          {`(function(e,t,n){if(e.snaptr)return;var a=e.snaptr=function(){
a.handleRequest?a.handleRequest.apply(a,arguments):a.queue.push(arguments)};
a.queue=[];var s='script';var r=t.createElement(s);r.async=!0;
r.src=n;var u=t.getElementsByTagName(s)[0];
u.parentNode.insertBefore(r,u);})(window,document,'https://sc-static.net/scevent.min.js');
snaptr('init','${snapchat}');snaptr('track','PAGE_VIEW');`}
        </Script>
      )}

      {anyGoogle && (
        <>
          {/* Pushed into `dataLayer` before gtag.js can drain it — see the docstring.
              Default DENIED first, then the visitor's actual answer as an update: that
              order is what Consent Mode expects, and it is what makes a page that loads
              before the answer is known behave correctly. */}
          <Script id="gtag-consent" strategy="afterInteractive">
            {`window.dataLayer=window.dataLayer||[];
window.gtag=window.gtag||function(){window.dataLayer.push(arguments);};
gtag('consent','default',{'ad_storage':'denied','ad_user_data':'denied','ad_personalization':'denied','analytics_storage':'denied','wait_for_update':500});
gtag('consent','update',${googleConsentPayload(consent.marketing, consent.analytics)});`}
          </Script>
          <Script
            id="gtag-src"
            strategy="afterInteractive"
            src={`https://www.googletagmanager.com/gtag/js?id=${googleAds || ga4}`}
          />
          <Script id="gtag-config" strategy="afterInteractive">
            {`gtag('js',new Date());
${ga4 ? `gtag('config','${ga4}');` : ""}
${googleAds ? `gtag('config','${googleAds}');` : ""}`}
          </Script>
        </>
      )}
    </>
  );
}
