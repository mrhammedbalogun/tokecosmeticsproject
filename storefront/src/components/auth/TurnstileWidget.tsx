"use client";

/**
 * Cloudflare Turnstile widget (Spin integration).
 *
 * EXPLICIT rendering, not the implicit `.cf-turnstile` scan: the scan runs once
 * at script load, so on a client-side navigation (/login → /register) a freshly
 * mounted container would never be rendered and the form could not obtain a
 * token. Each mount loads (or reuses) the script and renders its own widget.
 *
 * The rendered widget injects a hidden `cf-turnstile-response` input into the
 * enclosing form (Turnstile's `response-field`, on by default) — Server-Function
 * forms read the token from FormData. Fetch-based forms (checkout's SignInStep)
 * call `turnstileToken()` instead.
 *
 * Tokens are SINGLE-USE: after a failed submit the DOM still holds the redeemed
 * token, and resubmitting it is rejected as timeout-or-duplicate. Parents pass
 * `resetSignal` (any value that changes identity per failed attempt — the
 * useActionState state object works) and the widget resets itself for a fresh
 * token.
 *
 * Renders nothing when NEXT_PUBLIC_TURNSTILE_SITE_KEY is unset — the gate-off
 * deployment mode, matching the backend's unset TURNSTILE_SECRET.
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

// render=explicit switches the load-time DOM scan off, so the class + data
// attributes below are inert markers (kept for the Spin telemetry contract and
// for tests), not a second render path.
const SCRIPT_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

/** Plain script loader rather than `next/script`: the load must be sequenced
 * with the explicit `turnstile.render()` call below, and owning the tag keeps
 * that ordering in one visible place instead of split across a Script strategy.
 * One shared tag, deduped by src; the callback fires immediately when Turnstile
 * is already live, which covers client-side navigations between auth pages. */
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

/** The current widget token, for fetch-based submits. Undefined when the widget
 * never rendered (script blocked, gate off) — send nothing and let the backend
 * decide, so gate-off deployments keep the exact old request shape. */
export function turnstileToken(): string | undefined {
  try {
    return window.turnstile?.getResponse() || undefined;
  } catch {
    return undefined;
  }
}

export function TurnstileWidget({ resetSignal }: { resetSignal?: unknown }) {
  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
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
      action: "turnstile-spin-v2",
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

  // Skip the initial render — resetting a widget that hasn't issued a token yet
  // would just churn it. Only a CHANGE in resetSignal (a failed submit) resets.
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
      className="cf-turnstile"
      data-sitekey={siteKey}
      data-action="turnstile-spin-v2"
    />
  );
}
