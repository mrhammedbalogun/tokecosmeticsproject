"use client";

/**
 * "Have a friend's referral code?" — the manual path into attribution.
 *
 * Most referrals arrive by link (`?ref=` or `/r/CODE`), which needs no UI at all. This
 * exists for the other half of how people actually share: a code read out on a call,
 * typed from a story screenshot, or pasted from a WhatsApp message. Without it the
 * account page advertised a code that nothing could redeem.
 *
 * DELIBERATELY SEPARATE FROM THE COUPON FIELD, though they sit together and — since
 * 2026-08-27 — both now move the total. They remain separate because they are still
 * different things: a coupon is a campaign the shop is running, a referral code decides
 * who gets PAID as well as what the shopper saves, and only one of them can be refused
 * for being your own. Sharing one box would mean one field with two failure vocabularies.
 *
 * WHAT CHANGED WITH THE CUSTOMER DISCOUNT. A code now moves the total, because the
 * referred customer takes a percentage off their own goods — so a successful apply calls
 * `onApplied`, and the surrounding page re-quotes. Attribution itself still does NOT ride
 * the quote: the code goes into the httpOnly cookie and the BFF reads it back out on both
 * the quote and the placement, so what the browser ASKS for can still never decide who is
 * paid. This component never sees the totals; it only says "something changed".
 *
 * It is COLLAPSED by default. The overwhelming majority of shoppers have no code, and an
 * empty box labelled "referral code" invites people to hunt for one they do not have.
 *
 * RENDERED IN TWO PLACES: the cart page (`CartView`) and the checkout review step
 * (`ReviewStep`). Both are needed because two routes reach payment without ever passing
 * through /cart — "Buy now" on a product page (`BuyButtons`) and the mini-cart drawer's
 * checkout button (`CartDrawer`) — so a cart-only field is invisible to anyone who takes
 * either. See `variant` for the only difference between the two renderings.
 */
import { useState } from "react";

type Result =
  | { state: "idle" }
  | { state: "applying" }
  /** `discount` is the live percentage from `POST /api/referral`, or "" when the lookup
   *  could not tell us. Carried per-result rather than read from a prop because an Owner
   *  can set it to 0 from the admin at any time, and this message must never promise
   *  money off that the checkout will not give. */
  | { state: "ok"; name: string; discount: string }
  | { state: "bad"; reason: string };

/** "5" from "5.00"; "" from "0.00", a missing value, or anything unparseable. Mirrors
 *  `ratePercent` in lib/referral-terms.ts — imported from there would pull `lib/api`
 *  into this client bundle. */
function shownRate(raw: string | undefined): string {
  const rate = (raw ?? "").replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1");
  return Number(rate) > 0 ? rate : "";
}

const MESSAGES: Record<string, string> = {
  not_found: "We don't recognise that code — check it and try again.",
  // The backend distinguishes this so we can say something true rather than "invalid".
  self: "That's your own code. You can't earn commission on your own orders.",
  rate_limited: "Too many tries just now — give it a minute.",
  error: "We couldn't check that code — please try again.",
};

export function ReferralCodeField({
  initiallyOpen = false,
  variant = "card",
  onApplied,
}: {
  initiallyOpen?: boolean;
  /** Called after a code is successfully applied, so the page can re-quote and show the
   *  customer's discount. Optional: a caller that shows no totals has nothing to redraw. */
  onApplied?: () => void;
  /**
   * Where this is being rendered, which is only a chrome decision.
   *
   * "card" — the cart page, where the field is a free-standing block between the coupon
   * card and the order summary, so it wears its own border and background.
   * "inline" — the checkout review step, whose sections are separated by a top rule and
   * carry no box of their own. Keeping the card there would nest a box inside a box.
   *
   * Deliberately NOT two components: the behaviour (validate upstream, let the server
   * set the cookie, never touch the price) is the part that must not drift between the
   * two places a shopper can enter a code, and duplicating the markup is how it drifts.
   */
  variant?: "card" | "inline";
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const [code, setCode] = useState("");
  const [result, setResult] = useState<Result>({ state: "idle" });

  async function apply() {
    const value = code.trim();
    if (!value) return;
    setResult({ state: "applying" });
    try {
      const res = await fetch("/api/referral", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code: value }),
      });
      const data = await res.json();
      setResult(
        data.valid
          ? {
              state: "ok",
              name: data.referrer_name || "a friend",
              discount: shownRate(data.customer_discount_percent),
            }
          : { state: "bad", reason: data.reason || "error" },
      );
      // Only on success: a refused code left the cookie untouched, so there is nothing
      // new to fetch and a re-quote would just be a wasted round trip mid-checkout.
      if (data.valid) onApplied?.();
    } catch {
      setResult({ state: "bad", reason: "error" });
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-sm text-muted underline underline-offset-2 hover:text-foreground"
      >
        Have a friend&rsquo;s referral code?
      </button>
    );
  }

  return (
    <div
      className={
        variant === "card"
          ? "rounded-[var(--radius-card)] border border-line bg-surface p-5"
          : ""
      }
    >
      <label htmlFor="referral-code" className="mb-2 block text-sm font-medium">
        Friend&rsquo;s referral code
      </label>
      <div className="flex gap-2">
        <input
          id="referral-code"
          type="text"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void apply();
            }
          }}
          placeholder="e.g. AMINA7K3P"
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          // Uppercase on display only — the value is normalised server-side, so this is
          // purely so what the shopper sees matches the code on the card they read it from.
          className="min-w-0 flex-1 rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm uppercase placeholder:normal-case"
        />
        <button
          type="button"
          onClick={apply}
          disabled={!code.trim() || result.state === "applying"}
          className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          {result.state === "applying" ? "Checking…" : "Apply"}
        </button>
      </div>

      <p aria-live="polite" className="mt-2 text-sm">
        {result.state === "ok" && (
          <span className="text-accent-strong">
            ✓ You&rsquo;re shopping with {result.name}&rsquo;s link
            {result.discount
              ? ` — that\u2019s ${result.discount}% off for you, and commission for them.`
              : " — they\u2019ll earn commission on this order."}
          </span>
        )}
        {result.state === "bad" && (
          <span className="text-muted">{MESSAGES[result.reason] ?? MESSAGES.error}</span>
        )}
        {result.state === "idle" && (
          // Before applying, the rate is not known here — so this promises nothing and
          // the confirmation above names the actual number. It used to say the total
          // would NOT move, which was true until the customer discount shipped.
          <span className="text-muted">
            We&rsquo;ll credit the friend who sent you, and apply any discount you&rsquo;re
            due.
          </span>
        )}
      </p>
    </div>
  );
}
