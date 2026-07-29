"use client";

/**
 * Cloudflare Turnstile, for the two unauthenticated admin forms (`/login` and
 * `/accept-invite`). Behaviourally identical to the storefront's widget; the differences
 * are the env var it reads and the reasons written down here.
 *
 * ── A SEPARATE ADMIN WIDGET, NOT THE STOREFRONT'S ─────────────────────────────────
 *
 * Turnstile widgets are DOMAIN-SCOPED, and the admin is a new hostname — the storefront's
 * widget would simply error client-side before a token was ever minted. Beyond that
 * mechanical fact, a separate widget pairs with the `TURNSTILE_ADMIN_SECRET` indirection
 * already built into `apps/accounts/turnstile.admin_turnstile_secret`, which is what makes
 * the break-glass in `docs/runbooks/admin-gate.md` §2 able to drop the STAFF gate during a
 * siteverify outage without also dropping the customer gate.
 *
 * Creating the real widget needs Hammed in the Cloudflare dashboard. That is a LAUNCH
 * dependency, not a build one: Cloudflare publishes permanent test keys, and this whole
 * ceremony is verifiable end to end with them. See `README.md` for the pair to use in dev
 * (always-pass) and the pair that exercises the rejection path (always-fail). Production
 * cutover is swapping two environment values.
 *
 * Renders NOTHING when the site key is unset — the gate-off mode, matching an unset
 * `TURNSTILE_ADMIN_SECRET`/`TURNSTILE_SECRET` on the backend. The form then submits with
 * no `cf-turnstile-response` field and Django decides.
 *
 * EXPLICIT rendering, not the implicit `.cf-turnstile` scan: the scan runs once at script
 * load, so on a client-side navigation a freshly mounted container would never be rendered
 * and the form could not obtain a token.
 *
 * Tokens are SINGLE-USE: after a failed submit the DOM still holds the redeemed token and
 * resubmitting it is rejected as timeout-or-duplicate. Parents pass `resetSignal` (any
 * value whose identity changes per failed attempt — the `useActionState` state object
 * works) and the widget resets itself for a fresh token.
 */
import { useEffect, useRef, useState } from "react";

interface TurnstileApi {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string;
  remove: (id: string) => void;
  reset: (id?: string) => void;
  getResponse: (id?: string) => string | undefined;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const SCRIPT_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

/** Plain script tag rather than `next/script`: the load must be sequenced with the
 *  explicit `turnstile.render()` call below, and owning the tag keeps that ordering in one
 *  visible place. One shared tag, deduped by src. */
function loadTurnstile(onReady: () => void): void {
  if (window.turnstile) {
    onReady();
    return;
  }
  let tag = document.querySelector<HTMLScriptElement>(`script[src="${SCRIPT_SRC}"]`);
  if (!tag) {
    tag = document.createElement("script");
    tag.src = SCRIPT_SRC;
    tag.async = true;
    tag.defer = true;
    document.head.appendChild(tag);
  }
  tag.addEventListener("load", onReady, { once: true });
}

export function TurnstileWidget({ resetSignal }: { resetSignal?: unknown }) {
  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_ADMIN_SITE_KEY;
  const container = useRef<HTMLDivElement>(null);
  const widgetId = useRef<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!siteKey) return;
    let cancelled = false;
    loadTurnstile(() => {
      if (!cancelled) setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [siteKey]);

  useEffect(() => {
    if (!ready || !siteKey || !container.current || widgetId.current !== null) return;
    const turnstile = window.turnstile;
    if (!turnstile) return;
    widgetId.current = turnstile.render(container.current, {
      sitekey: siteKey,
      action: "toke-admin",
    });
    return () => {
      if (widgetId.current !== null) {
        try {
          turnstile.remove(widgetId.current);
        } catch {
          // Removing an already-gone widget must not break unmount.
        }
        widgetId.current = null;
      }
    };
  }, [ready, siteKey]);

  // Skip the initial render — resetting a widget that has not issued a token yet would
  // just churn it. Only a CHANGE in resetSignal (a failed submit) resets.
  const firstSignal = useRef(true);
  useEffect(() => {
    if (firstSignal.current) {
      firstSignal.current = false;
      return;
    }
    try {
      window.turnstile?.reset(widgetId.current ?? undefined);
    } catch {
      // A reset race (widget mid-refresh) is harmless; the next render recovers.
    }
  }, [resetSignal]);

  if (!siteKey) return null;

  return (
    <div
      ref={container}
      className="cf-turnstile mt-4"
      data-sitekey={siteKey}
      data-action="toke-admin"
    />
  );
}
