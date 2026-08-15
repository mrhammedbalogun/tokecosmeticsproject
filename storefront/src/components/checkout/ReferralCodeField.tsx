"use client";

/**
 * "Have a friend's referral code?" — the manual path into attribution.
 *
 * Most referrals arrive by link (`?ref=` or `/r/CODE`), which needs no UI at all. This
 * exists for the other half of how people actually share: a code read out on a call,
 * typed from a story screenshot, or pasted from a WhatsApp message. Without it the
 * account page advertised a code that nothing could redeem.
 *
 * DELIBERATELY SEPARATE FROM THE COUPON FIELD, though they sit together. They look alike
 * and do unrelated things: a coupon changes what the shopper pays and must therefore
 * re-quote the cart; a referral code changes who gets paid commission afterwards and
 * changes the shopper's total by exactly nothing. Sharing one box would mean explaining
 * why one "code" moves the price and another does not, and would put attribution on the
 * cart-quote path where a re-quote could drop it.
 *
 * It is COLLAPSED by default. The overwhelming majority of shoppers have no code, and an
 * empty box labelled "referral code" invites people to hunt for one they do not have —
 * which is how you get a checkout page that feels like it is withholding a discount.
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
  | { state: "ok"; name: string }
  | { state: "bad"; reason: string };

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
}: {
  initiallyOpen?: boolean;
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
          ? { state: "ok", name: data.referrer_name || "a friend" }
          : { state: "bad", reason: data.reason || "error" },
      );
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
            ✓ You&rsquo;re shopping with {result.name}&rsquo;s link — they&rsquo;ll earn
            commission on this order.
          </span>
        )}
        {result.state === "bad" && (
          <span className="text-muted">{MESSAGES[result.reason] ?? MESSAGES.error}</span>
        )}
        {result.state === "idle" && (
          // Said up front, because a shopper typing a "code" into a cart reasonably
          // expects money off and would otherwise feel misled when the total does not move.
          <span className="text-muted">
            This won&rsquo;t change your total — it just credits the friend who sent you.
          </span>
        )}
      </p>
    </div>
  );
}
