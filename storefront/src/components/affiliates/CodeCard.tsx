"use client";

/**
 * The card that carries this page's whole argument.
 *
 * ── WHY A PERSONALISED WIDGET ON A MARKETING PAGE ───────────────────────────────────
 *
 * Every affiliate page on the internet ends in "Apply now" — including the one this
 * replaces (tokecosmetics.com/affiliates-2/: "Apply Now →", "Apply via Email"). Toke's
 * programme has NO APPLICATION. `services.ensure_profile` mints a code the first time a
 * customer looks, so an account IS enrolment.
 *
 * A page can claim that in a sentence, or it can show the customer their own live code
 * while they are reading the sentence. This does the second. Signed in, the card is the
 * real link, copyable, right here — the reader never has to be persuaded that they are
 * already in, because they can see their code.
 *
 * ── THREE STATES, AND THE THIRD IS THE ONE THAT MATTERS ─────────────────────────────
 *
 * `signedIn` comes from the access-token COOKIE, exactly as the site header decides it,
 * while `code` comes from a fetch that can fail on an expired token. So "signed in but no
 * code" is a real state, not a defensive nicety, and showing it "Create an account" would
 * contradict the header three inches above. It gets its own copy and a link to the
 * dashboard instead.
 *
 * Copy behaviour matches `referrals/ShareCard.tsx` deliberately, fallback included:
 * `navigator.clipboard` is undefined on insecure origins and rejects when the document is
 * not focused, and a copy button that silently does nothing sends someone away believing
 * they have a link.
 */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

type Props =
  | { state: "anonymous" }
  | { state: "no-code" }
  | { state: "ready"; code: string; shareUrl: string };

export function CodeCard(props: Props) {
  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface p-6 shadow-[0_18px_50px_-30px_rgba(26,26,26,0.45)] sm:p-8">
      <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
        Your link
      </p>
      {props.state === "ready" ? <Ready code={props.code} shareUrl={props.shareUrl} /> : null}
      {props.state === "no-code" ? <NoCode /> : null}
      {props.state === "anonymous" ? <Anonymous /> : null}
    </div>
  );
}

function Ready({ code, shareUrl }: { code: string; shareUrl: string }) {
  const [copied, setCopied] = useState<"idle" | "done" | "manual">("idle");
  const inputRef = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  return (
    <>
      <p className="mt-3 break-all font-mono text-2xl tracking-tight sm:text-3xl">{code}</p>
      <label className="mt-5 block">
        <span className="sr-only">Your referral link</span>
        <input
          ref={inputRef}
          readOnly
          value={shareUrl}
          onFocus={(e) => e.currentTarget.select()}
          className="w-full rounded-full border border-line bg-background px-4 py-2.5 text-sm text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        />
      </label>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={copy}
          className="rounded-full bg-accent px-7 py-3 text-xs font-medium uppercase tracking-[0.14em] text-surface transition hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Copy link
        </button>
        <Link
          href="/account/referrals"
          className="text-sm font-medium text-accent underline underline-offset-4 transition hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Earnings and payouts
        </Link>
      </div>
      {/* aria-live so the confirmation reaches a screen reader; the height is reserved
          whatever the state, so confirming never nudges the layout. */}
      <p aria-live="polite" className="mt-3 min-h-5 text-xs text-muted">
        {copied === "done" && "Copied to your clipboard."}
        {copied === "manual" && "Selected — press Ctrl/⌘ + C to copy."}
      </p>
    </>
  );
}

function NoCode() {
  return (
    <>
      <p className="mt-4 font-display text-xl uppercase tracking-[0.1em]">
        It&rsquo;s in your account
      </p>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        We couldn&rsquo;t load your code just now. It hasn&rsquo;t gone anywhere — open
        your referrals page and it&rsquo;ll be waiting.
      </p>
      <Link
        href="/account/referrals"
        className="mt-6 inline-block rounded-full bg-accent px-7 py-3 text-xs font-medium uppercase tracking-[0.14em] text-surface transition hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        Open my referrals
      </Link>
    </>
  );
}

function Anonymous() {
  return (
    <>
      {/* A SPECIMEN, not a lock icon. The point being made is "a code like this is
          already reserved for you", and a redacted example says that far better than a
          padlock, which says "you are not allowed". */}
      <p className="mt-3 font-mono text-2xl tracking-tight text-muted sm:text-3xl" aria-hidden>
        AMINA<span className="text-muted/40">••••</span>
      </p>
      <p className="mt-4 text-sm leading-relaxed text-muted">
        Your code is made from your name the first time you look. Create an account and
        it&rsquo;s yours — there&rsquo;s no application and nothing to wait for.
      </p>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Link
          href="/register"
          className="rounded-full bg-accent px-7 py-3 text-xs font-medium uppercase tracking-[0.14em] text-surface transition hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Create an account
        </Link>
        <Link
          href="/login?next=/affiliates"
          className="text-sm font-medium text-accent underline underline-offset-4 transition hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          I already have one
        </Link>
      </div>
    </>
  );
}
