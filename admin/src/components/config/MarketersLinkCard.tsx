"use client";

/**
 * The marketers' price-list link (Plan-39 addendum, 2026-08-20): a copyable
 * pointer to the PUBLIC `/partner/rates` page, so staff never have to remember
 * the URL to onboard a marketer. The absolute URL is composed from
 * `window.location.origin` — this admin serves from more than one host (prod,
 * previews, localhost), and the copied link must match the one the reader is
 * on. Read via `useSyncExternalStore` with the bare path as the server
 * snapshot: hydration stays honest and the lint's no-setState-in-effect rule
 * stays satisfied (the origin never changes, so the subscription is inert).
 */
import { useState, useSyncExternalStore } from "react";

const RATES_PATH = "/partner/rates";

const subscribeNever = () => () => {};

export function MarketersLinkCard() {
  const url = useSyncExternalStore(
    subscribeNever,
    () => `${window.location.origin}${RATES_PATH}`,
    () => RATES_PATH,
  );
  const [copied, setCopied] = useState<"idle" | "done" | "failed">("idle");

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied("done");
    } catch {
      // Clipboard access can be refused (permissions, http): the URL stays
      // visible and selectable, so the fallback is "select it yourself".
      setCopied("failed");
    }
    window.setTimeout(() => setCopied("idle"), 2000);
  }

  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
      <p className="text-sm font-semibold">Marketers&rsquo; price list</p>
      <p className="mt-0.5 text-sm text-muted">
        A public, read-only page of every live partner rate — no login. Share it
        with anyone who quotes delivery fees; it always shows exactly what
        checkout charges right now.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <code className="select-all rounded-md border border-line bg-canvas px-3 py-2 text-xs">
          {url}
        </code>
        <button
          type="button"
          onClick={copy}
          className="rounded-md border border-line px-3 py-2 text-sm transition-colors hover:border-accent/60"
        >
          {copied === "done" ? "Copied ✓" : copied === "failed" ? "Copy failed — select it" : "Copy link"}
        </button>
        <a
          href={RATES_PATH}
          target="_blank"
          rel="noreferrer"
          className="rounded-md border border-line px-3 py-2 text-sm text-muted transition-colors hover:border-accent/60 hover:text-foreground"
        >
          Open ↗
        </a>
      </div>
    </div>
  );
}
