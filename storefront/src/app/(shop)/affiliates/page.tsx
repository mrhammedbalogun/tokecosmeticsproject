import type { Metadata } from "next";
import Link from "next/link";
import { cookies } from "next/headers";
import { CodeCard } from "@/components/affiliates/CodeCard";
import { SaleTimeline } from "@/components/affiliates/SaleTimeline";
import { TierPanel } from "@/components/affiliates/TierPanel";
import { TileMedia, bannerFor } from "@/components/home/TileMedia";
import { FadeUp } from "@/components/motion/Motion";
import { apiFetch } from "@/lib/api";
import { getHomepage } from "@/lib/cms";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY, getMarkets, normalizeCountry } from "@/lib/country";
import {
  getReferralTerms,
  ratePercent,
  thresholdsForMarket,
  type ReferralTerms,
} from "@/lib/referral-terms";
import { getAccessToken } from "@/lib/session";
import { pageMetadata } from "@/lib/seo";

/**
 * `/affiliates` — the public referral programme page.
 *
 * ── THE THING THIS PAGE IS ARGUING ──────────────────────────────────────────────────
 *
 * The WordPress page it replaces sells exclusivity: "we invite creators, curators and
 * connoisseurs", "Apply Now →", "Apply via Email". None of that is true of the programme
 * that was actually built. `services.ensure_profile` mints a code the first time a
 * customer looks, so THERE IS NO APPLICATION — an account is enrolment, which is a
 * better offer than the one being advertised. Every layout beat from Hammed's reference
 * design is kept; the one that said "apply" now says "you already have it", and
 * `CodeCard` proves it by showing a signed-in reader their own live code.
 *
 * ── THE TYPE RULE ───────────────────────────────────────────────────────────────────
 *
 * UPPERCASE ON WIDE TRACKING IS THE DISPLAY VOICE; PLAYFAIR CARRIES IT. That is the
 * borrow from Hammed's reference — its personality is almost entirely wide-tracked
 * capitals — adapted to this shop's face rather than its.
 *
 * The first draft tried to set the headings in Inter to match the reference exactly, and
 * `globals.css` silently won: it styles `h1, h2, h3` by ELEMENT, so every heading in the
 * storefront is Playfair whether or not a class says otherwise. Rendering it proved the
 * stylesheet right — tracked-out Playfair capitals read as Toke, and an all-sans page
 * would have been the only one on the site. The rule was changed to match the code, not
 * the other way round.
 *
 * Inter keeps the small stuff: eyebrows, tile labels, buttons — all uppercase on the
 * same tracking, so the two families are doing scale rather than arguing.
 *
 * ── NO NUMBER ON THIS PAGE IS WRITTEN IN THIS FILE ──────────────────────────────────
 *
 * Rate, tracking window, holding period, payout minimums and the elite tier arrive from
 * `/referrals/terms/`, which serves the Django settings the commission is calculated
 * from. This page is advertising and the shop is bound by it; a hardcoded "10%" here
 * would be a promise stored where it cannot change when the promise does.
 *
 * ── WHY THE FETCH IS TOLERANT ───────────────────────────────────────────────────────
 *
 * `signedIn` comes from the access-token cookie (the same way `Header` decides it) and
 * the code comes from an authenticated fetch that can 401 on a stale token. This page
 * must never bounce a reader to /login — it is a marketing page and the reader may have
 * arrived from an ad. `fetchWithAuthOrBounce` is deliberately NOT used: a failure
 * downgrades the card, never the page.
 */
export const metadata: Metadata = pageMetadata({
  title: "Affiliates",
  description:
    "Every Toke Cosmetics account comes with a referral link. Share it, earn commission on what your people spend, and get paid to your bank.",
  path: "/affiliates",
});

interface Overview {
  code: string;
  share_url: string;
  is_blocked: boolean;
}

export default async function AffiliatesPage() {
  const jar = await cookies();
  const signedIn = Boolean(await getAccessToken());
  const country = normalizeCountry(jar.get(COUNTRY_COOKIE)?.value, []) || DEFAULT_COUNTRY;

  const [terms, markets, overview, homepage] = await Promise.all([
    getReferralTerms(),
    getMarkets().catch(() => []),
    loadOverview(),
    // Banners live behind the homepage endpoint, which serves EVERY live banner rather
    // than only the homepage's — see the `affiliate_hero` placement comment on the model.
    getHomepage(country),
  ]);

  const market = normalizeCountry(jar.get(COUNTRY_COOKIE)?.value, markets.map((m) => m.code))
    || DEFAULT_COUNTRY;
  const currency = markets.find((m) => m.code === market)?.currency.code;

  // A BLOCKED referrer is treated as signed-in-without-a-code rather than shown a link
  // that earns nothing. They are told the real reason on their own dashboard, which is
  // where a suspension belongs — not in the middle of a marketing page.
  const cardState: Parameters<typeof CodeCard>[0] =
    overview && !overview.is_blocked
      ? { state: "ready", code: overview.code, shareUrl: overview.share_url }
      : signedIn
        ? { state: "no-code" }
        : { state: "anonymous" };

  const banners = homepage?.banners ?? [];
  const heroBanner = bannerFor(banners, "affiliate_hero");
  const tier = terms.elite_tiers[0];

  return (
    <div className="bg-beige">
      <HeroBand banner={heroBanner} />
      <Opening cardState={cardState} signedIn={signedIn} />
      <OfferRow terms={terms} currency={currency} />
      <SaleTimeline cookieDays={terms.cookie_days} holdDays={terms.hold_days} />
      {tier && <TierPanel tier={tier} banner={bannerFor(banners, "affiliate_tier")} />}
      <FinePrint terms={terms} currency={currency} />
      <Closing signedIn={signedIn} />
    </div>
  );
}

/** The overview, or null. Never throws, never redirects — see the page docstring.
 *
 * This is also the call that ENROLS somebody: `ReferralOverviewView` runs
 * `ensure_profile`, so a signed-in customer who merely reads this page leaves it with a
 * working code. That is the programme working as designed, not a side effect to remove. */
async function loadOverview(): Promise<Overview | null> {
  const token = await getAccessToken();
  if (!token) return null;
  try {
    return await apiFetch<Overview>("/me/referrals/", { token, cache: "no-store" });
  } catch {
    return null;
  }
}

/**
 * The cinematic opener.
 *
 * NOTHING IS RENDERED WITHOUT ARTWORK. `TileMedia` falls back to a brand gradient, which
 * is right on the homepage where a tile has a reserved slot in a grid; here it would put
 * a 55vh empty green stripe above the headline, and a reader cannot tell "not uploaded
 * yet" from "broken". The page is composed to be finished without it — the opener is a
 * gain when the artwork exists, never a hole when it doesn't.
 */
function HeroBand({ banner }: { banner: ReturnType<typeof bannerFor> }) {
  if (!banner?.image && !banner?.mobile_image && !banner?.video_url) return null;
  return (
    <div className="relative h-[42vh] min-h-[280px] w-full overflow-hidden sm:h-[55vh]">
      <TileMedia banner={banner} tone="from-[#14401f] to-[#0b2413]" sizes="100vw" />
    </div>
  );
}

function Opening({
  cardState,
  signedIn,
}: {
  cardState: Parameters<typeof CodeCard>[0];
  signedIn: boolean;
}) {
  return (
    <section className="wrap grid items-center gap-14 py-20 sm:py-28 lg:grid-cols-[1.1fr_0.9fr] lg:gap-20">
      <div>
        <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
          Toke affiliate programme
        </p>
        {/* The reference opens on one enormous tracked word — PARTNER — under which sits
            "Apply Now". Same beat, opposite claim, because ours is the true one. The dot
            is kept: it is the detail that stops a wide-tracked word reading as a banner
            headline and makes it read as a mark. */}
        <h1 className="mt-7 text-[3.1rem] uppercase leading-[0.92] tracking-[0.06em] sm:text-7xl lg:text-8xl">
          Already
          <br />
          in
          <span aria-hidden className="text-accent">.</span>
        </h1>
        <hr className="mt-8 max-w-md border-line" />
        <p className="mt-8 max-w-md text-sm leading-relaxed text-muted">
          Every Toke Cosmetics account carries a referral link. No forms, no approval, no
          minimum following — share it with the people who ask what you use, and you earn
          on what they spend.
        </p>
        {!signedIn && (
          <p className="mt-3 max-w-md text-sm leading-relaxed text-muted">
            The only thing standing between you and a code is an account.
          </p>
        )}
      </div>
      <FadeUp>
        <CodeCard {...cardState} />
      </FadeUp>
    </section>
  );
}

/**
 * The offer, in three figures — the reference's strongest scanning device, kept.
 *
 * The third tile is the one that had to change: the reference reads "₦20k MIN PAYOUT",
 * which is only true in Nigeria. This shop pays four currencies and never converts
 * between them, so the tile shows the minimum for the market the reader is actually
 * shopping in, and the full table sits in the fine print below.
 */
function OfferRow({ terms, currency }: { terms: ReferralTerms; currency: string | undefined }) {
  const mine = thresholdsForMarket(terms.payout_thresholds, currency)[0];
  const facts = [
    {
      figure: `${ratePercent(terms.commission_percent)}%`,
      label: "Commission",
      body: "Of every qualifying sale made through your link, on the products in the order.",
    },
    {
      figure: `${terms.cookie_days} days`,
      label: "Tracking window",
      body: "You keep the credit long after the first click, not just for that visit.",
    },
    {
      figure: mine?.amount_display ?? "—",
      label: "Minimum payout",
      body: `Request a payout once your ${mine?.currency ?? ""} balance clears it. Balances roll over until they do.`,
    },
  ];

  return (
    <section aria-labelledby="offer-heading" className="wrap pb-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
        The offer
      </p>
      <h2 id="offer-heading" className="mt-4 text-2xl uppercase tracking-[0.14em] sm:text-[1.75rem]">
        What you earn
      </h2>
      <FadeUp>
        <dl className="mt-10 grid gap-px overflow-hidden rounded-[var(--radius-card)] border border-line bg-line sm:grid-cols-3">
          {facts.map((fact) => (
            <div key={fact.label} className="bg-surface p-8">
              <dt className="font-display text-4xl text-accent-strong">{fact.figure}</dt>
              <dd>
                <p className="mt-4 text-[11px] font-medium uppercase tracking-[0.16em]">
                  {fact.label}
                </p>
                <p className="mt-2 text-sm leading-relaxed text-muted">{fact.body}</p>
              </dd>
            </div>
          ))}
        </dl>
      </FadeUp>
    </section>
  );
}

/**
 * The fine print.
 *
 * NOT behind a disclosure. `HowItWorks` on the signed-in dashboard puts these in a
 * `<details>`, which is right for somebody already earning who has read them once. On a
 * page persuading somebody to start, burying the conditions is how you build a support
 * queue — every line here is one a referrer would otherwise learn from a balance smaller
 * than they expected.
 *
 * Payment TIMING is deliberately absent: the timeline above owns it.
 */
function FinePrint({ terms, currency }: { terms: ReferralTerms; currency: string | undefined }) {
  const thresholds = thresholdsForMarket(terms.payout_thresholds, currency);
  const blocks = [
    {
      label: "Responsibilities",
      body: "You're representing Toke Cosmetics, so promote it the way you'd talk about it — honestly. Say when a post is paid: a simple #ad or #partner is all the advertising rules ask for, and it costs you nothing.",
    },
    {
      label: "Qualifying purchases",
      body: "Commission is calculated on the products after any discount — delivery charges and tax aren't included — and the order has to be paid for and dispatched before it counts. If it's returned, the commission is reversed. You can't use your own link, and orders from another account with your email or phone number don't earn either.",
    },
  ];

  return (
    <section aria-labelledby="fineprint-heading" className="wrap pb-20 sm:pb-28">
      <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
        The fine print
      </p>
      <h2
        id="fineprint-heading"
        className="mt-4 text-2xl uppercase tracking-[0.14em] sm:text-[1.75rem]"
      >
        Worth knowing before you share it
      </h2>

      <div className="mt-12 grid gap-12 border-t border-line pt-10 lg:grid-cols-[1.5fr_1fr] lg:gap-20">
        <dl className="grid gap-10 sm:grid-cols-2">
          {blocks.map((block) => (
            <div key={block.label}>
              <dt className="flex items-center gap-3 text-[11px] font-medium uppercase tracking-[0.16em]">
                <span aria-hidden className="h-px w-6 bg-foreground" />
                {block.label}
              </dt>
              <dd className="mt-4 text-sm leading-relaxed text-muted">{block.body}</dd>
            </div>
          ))}
        </dl>

        {/* Every currency, because a naira minimum shown alone to somebody shopping in
            pounds reads as "£20,000" at a glance. Their own market leads. */}
        <div>
          <p className="flex items-center gap-3 text-[11px] font-medium uppercase tracking-[0.16em]">
            <span aria-hidden className="h-px w-6 bg-foreground" />
            Payout minimums
          </p>
          <p className="mt-4 text-sm leading-relaxed text-muted">
            Each currency is earned and paid separately — we never convert between them.
          </p>
          <dl className="mt-6 grid gap-3">
            {thresholds.map((t, i) => (
              <div
                key={t.currency}
                className="flex items-baseline justify-between gap-4 border-b border-line pb-3 last:border-b-0"
              >
                <dt className={i === 0 ? "text-sm font-medium" : "text-sm text-muted"}>
                  {t.currency}
                </dt>
                <dd
                  className={`font-display text-xl ${i === 0 ? "text-accent-strong" : "text-muted"}`}
                >
                  {t.amount_display}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>

      {/* DEAD UNTIL THE TERMS PAGE EXISTS — Hammed's call, 2026-08-16. `/page/terms` is a
          CMS page and production has no CMS rows at all, so this 404s today. It is here
          rather than omitted so the link starts working the moment the page is written,
          with no second edit to remember. */}
      <Link
        href="/page/terms"
        className="mt-12 inline-flex items-center gap-2 border-b border-foreground pb-1 text-[11px] font-medium uppercase tracking-[0.16em] transition hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        Read the full terms
        <span aria-hidden>↗</span>
      </Link>
    </section>
  );
}

function Closing({ signedIn }: { signedIn: boolean }) {
  return (
    <section className="wrap border-t border-line py-20 text-center sm:py-28">
      <FadeUp>
        <h2 className="mx-auto max-w-3xl text-3xl uppercase leading-[1.15] tracking-[0.08em] sm:text-5xl">
          {signedIn ? "Go and share it" : "Make an account, get a link"}
        </h2>
        <p className="mx-auto mt-6 max-w-md text-sm leading-relaxed text-muted">
          {signedIn
            ? "Track what you've earned, add the account you want paying, and request a payout whenever your balance clears the minimum."
            : "It takes a minute, and it's the same account you'd use to order. Your referral code is waiting on the other side of it."}
        </p>
        <Link
          href={signedIn ? "/account/referrals" : "/register"}
          className="mt-10 inline-block rounded-full bg-accent px-10 py-4 text-sm font-medium uppercase tracking-[0.14em] text-surface transition hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          {signedIn ? "Open my referrals" : "Create an account"}
        </Link>
      </FadeUp>
    </section>
  );
}
