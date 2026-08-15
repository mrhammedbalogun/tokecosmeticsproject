"use client";

/**
 * The referrer's link, and every reasonable way to get it out of the browser.
 *
 * This component is the whole product for most customers — someone who never opens the
 * activity table still opens this to grab their link — so it gets the visual weight and
 * the fussy details: a big monospace code that reads correctly over the phone, copy
 * feedback that confirms without moving the layout, and the native share sheet on mobile
 * where it exists.
 *
 * WHY THE COPY BUTTON HAS A FALLBACK. `navigator.clipboard` is undefined on insecure
 * origins and can reject when the document is not focused; a copy button that silently
 * does nothing is worse than no button, because the customer walks away believing they
 * have a link on their clipboard. On failure the input is selected instead, so ⌘C still
 * works and the state says so.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

/**
 * Whether this browser has a native share sheet.
 *
 * `useSyncExternalStore` rather than a `useEffect` + `setState` pair: `navigator` does
 * not exist while rendering on the server, so the answer genuinely differs between the
 * server snapshot (always false) and the client's — which is exactly the case this hook
 * exists for, and it avoids the cascading render an effect-then-setState causes.
 *
 * `subscribe` is a no-op returning a no-op: the capability cannot change during a
 * session, so there is nothing to subscribe to. The store is read once and never
 * invalidated.
 */
const NEVER_CHANGES = () => () => {};
const hasNativeShare = () =>
  typeof navigator !== "undefined" && typeof navigator.share === "function";
const noNativeShareOnServer = () => false;

const SHARE_TEXT =
  "I use Toke Cosmetics for my skin — shop with my link and see what it does for yours.";

export function ShareCard({
  code,
  shareUrl,
  commissionPercent,
}: {
  code: string;
  shareUrl: string;
  commissionPercent: string;
}) {
  const [copied, setCopied] = useState<"idle" | "done" | "manual">("idle");
  const canNativeShare = useSyncExternalStore(
    NEVER_CHANGES, hasNativeShare, noNativeShareOnServer,
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // A pending "Copied!" timeout that fires after unmount would set state on a dead
  // component; clearing on unmount is the cheap way to never think about it again.
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied("done");
    } catch {
      inputRef.current?.select();
      setCopied("manual");
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied("idle"), 2500);
  }

  async function nativeShare() {
    try {
      await navigator.share({ title: "Toke Cosmetics", text: SHARE_TEXT, url: shareUrl });
    } catch {
      // AbortError when the sheet is dismissed is the normal case, not a failure.
    }
  }

  return (
    <section className="overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface">
      {/* The green band carries the brand's primary accent; everything below it stays
          calm. "Restrained, expensive" is the brief — one saturated surface, not five. */}
      <div className="bg-accent px-6 py-7 text-white sm:px-8">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-white/70">
          Your referral link
        </p>
        <h2 className="mt-2 font-display text-2xl leading-snug sm:text-3xl">
          Earn {commissionPercent}% every time someone shops with your link
        </h2>

        <div className="mt-5 flex flex-col gap-2 sm:flex-row">
          <label htmlFor="referral-link" className="sr-only">
            Your referral link
          </label>
          <input
            id="referral-link"
            ref={inputRef}
            readOnly
            value={shareUrl}
            onFocus={(e) => e.currentTarget.select()}
            className="min-w-0 flex-1 rounded-[var(--radius-card)] border border-white/25 bg-white/10 px-3 py-2.5 font-mono text-sm text-white placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-white/50"
          />
          <button
            type="button"
            onClick={copy}
            className="shrink-0 rounded-[var(--radius-card)] bg-white px-5 py-2.5 text-sm font-medium text-accent-strong transition-colors hover:bg-white/90"
          >
            {copied === "done" ? "Copied ✓" : copied === "manual" ? "Press ⌘C" : "Copy link"}
          </button>
        </div>

        {/* Announced, not just coloured: the copy result is the one piece of feedback a
            screen-reader user has no other way to perceive. */}
        <p aria-live="polite" className="mt-2 min-h-[1.25rem] text-xs text-white/80">
          {copied === "done" && "Link copied to your clipboard."}
          {copied === "manual" && "We couldn't copy automatically — the link is selected, press ⌘C."}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2 px-6 py-4 sm:px-8">
        <span className="mr-1 text-sm text-muted">Share to</span>

        <ShareLink
          label="WhatsApp"
          href={`https://wa.me/?text=${encodeURIComponent(`${SHARE_TEXT} ${shareUrl}`)}`}
        />
        <ShareLink
          label="Instagram"
          href="https://www.instagram.com/"
          // Instagram has no share-by-URL endpoint at all — a link that pretends to
          // prefill would just drop the customer on their feed wondering what happened.
          // This one says plainly that the caption has to be pasted.
          hint="Copy your link, then paste it into your bio or story"
        />
        <ShareLink
          label="X"
          href={`https://twitter.com/intent/tweet?text=${encodeURIComponent(SHARE_TEXT)}&url=${encodeURIComponent(shareUrl)}`}
        />
        <ShareLink
          label="Facebook"
          href={`https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(shareUrl)}`}
        />
        <ShareLink
          label="Email"
          href={`mailto:?subject=${encodeURIComponent("You should try Toke Cosmetics")}&body=${encodeURIComponent(`${SHARE_TEXT}\n\n${shareUrl}`)}`}
          external={false}
        />

        {canNativeShare && (
          <button
            type="button"
            onClick={nativeShare}
            className="rounded-full border border-line px-3.5 py-1.5 text-sm transition-colors hover:bg-beige"
          >
            More…
          </button>
        )}

        <span className="ml-auto text-sm text-muted">
          or your code{" "}
          <strong className="font-mono font-semibold tracking-wide text-foreground">{code}</strong>
          <span className="block text-xs">friends can enter it in the cart</span>
        </span>
      </div>
    </section>
  );
}

function ShareLink({
  label,
  href,
  hint,
  external = true,
}: {
  label: string;
  href: string;
  hint?: string;
  external?: boolean;
}) {
  return (
    <a
      href={href}
      title={hint}
      // noreferrer alongside noopener: these are outbound social links from a page that
      // is noindex and behind a login, and there is no reason to hand the referrer URL
      // of a customer's account page to a third party.
      {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      className="rounded-full border border-line px-3.5 py-1.5 text-sm transition-colors hover:bg-beige"
    >
      {label}
    </a>
  );
}
