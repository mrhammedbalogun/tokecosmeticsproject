"use client";

/**
 * The live storefront, framed inside /home-content (Phase 3 of the 2026-08-06 rework).
 *
 * This is the real shop — the same URL a customer gets — not a mock render, so what it
 * shows is the truth including fixtures, scheduling and geo-targeting (it browses as
 * the admin's own country). The storefront's frame-ancestors allowlists this app for
 * exactly this purpose (`storefront/src/lib/csp.ts`).
 *
 * Phone mode narrows the frame to 390px (iPhone-ish), which is ALSO how you preview a
 * tile's phone image: the storefront swaps crops on its own media query. Collapsed by
 * default — the iframe loads the whole shop, and that is not a cost every page view of
 * the editor should pay.
 */
import { useState } from "react";

export function StorefrontPreview({ url }: { url: string }) {
  const [open, setOpen] = useState(false);
  const [device, setDevice] = useState<"desktop" | "phone">("desktop");
  // Bumping the key remounts the iframe — the "did my edit land?" refresh.
  const [refreshKey, setRefreshKey] = useState(0);

  const btn = (active: boolean) =>
    `rounded border px-2.5 py-1 text-xs ${
      active ? "border-accent font-medium text-accent" : "border-line text-muted hover:border-accent"
    }`;

  return (
    <div className="rounded-[var(--radius-card)] border border-line">
      <div className="flex flex-wrap items-center gap-2 p-3">
        <button type="button" onClick={() => setOpen((o) => !o)} className={btn(open)}>
          {open ? "Hide preview" : "Show live preview"}
        </button>
        {open && (
          <>
            <button type="button" onClick={() => setDevice("desktop")} className={btn(device === "desktop")}>
              Desktop
            </button>
            <button type="button" onClick={() => setDevice("phone")} className={btn(device === "phone")}>
              Phone
            </button>
            <button
              type="button"
              onClick={() => setRefreshKey((k) => k + 1)}
              className="rounded border border-line px-2.5 py-1 text-xs text-muted hover:border-accent"
            >
              Refresh
            </button>
          </>
        )}
        <span className="flex-1" />
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-muted underline underline-offset-2 hover:text-accent"
        >
          Open the shop in a new tab ↗
        </a>
      </div>
      {open && (
        <div className="flex justify-center border-t border-line bg-surface p-3">
          <iframe
            key={refreshKey}
            src={url}
            title="Storefront preview"
            className={`h-[70vh] rounded border border-line bg-white ${
              device === "phone" ? "w-[390px]" : "w-full"
            }`}
          />
        </div>
      )}
    </div>
  );
}
