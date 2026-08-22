"use client";

/**
 * One shop, as a card (Plan-42).
 *
 * ── THE HIERARCHY IS DELIBERATE ─────────────────────────────────────────────────────
 *
 * Marker and badge on one quiet line, then the name in Playfair across the full width,
 * then address and hours as body text, then the actions. The index is set as a hairline
 * marker rather than a bold "1." because it is an aid to reading a list aloud over the
 * phone ("the second one") and nothing more — it must not compete with the shop's name.
 *
 * ── EVERY ACTION IS A REAL LINK ─────────────────────────────────────────────────────
 *
 * `tel:` dials on a phone and opens the desktop's handler elsewhere; `wa.me` and the
 * maps URL are composed by the API (`stores/services.py`) rather than here, so the
 * admin and the storefront cannot drift about what a "Get directions" link points at.
 * The DIALLABLE E.164 value is what every link carries; the prettified national form
 * is only ever the text between the tags.
 */
import type { StoreCardData } from "@/lib/stores";

export function StoreCard({ store, index }: { store: StoreCardData; index: number }) {
  const isToke = store.store_type === "toke_store";
  // "Alimosho, Lagos" — the LGA where there is one, the free-text city where there is
  // not (GB/US/CA have no LGAs; see `stores.models.city_text`).
  const locality = [store.area || store.city, store.state].filter(Boolean).join(", ");

  return (
    <article className="group relative flex h-full flex-col rounded-[var(--radius-card)] border border-line bg-surface p-6 transition-all duration-300 hover:-translate-y-0.5 hover:border-accent/30 hover:shadow-lg motion-reduce:transform-none motion-reduce:transition-none sm:p-7">
      {/* The badge sits on the marker's line rather than beside the name. Sharing a row
          with a two-word badge left "Beauty Hub Alimosho" three lines tall in a
          three-column grid — the name is the most prominent thing on the card, so it
          gets the full width and the badge gets the line nobody was using. */}
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium tabular-nums tracking-[0.2em] text-muted">
          {String(index).padStart(2, "0")}
        </span>
        <StoreTypeBadge label={store.store_type_label} isToke={isToke} />
      </div>
      <h3 className="mt-3 font-display text-xl leading-snug text-balance break-words text-foreground sm:text-2xl">
        {store.name}
      </h3>

      <dl className="mt-5 space-y-4 text-sm">
        <div className="flex gap-3">
          <PinIcon />
          <div className="min-w-0">
            <dt className="sr-only">Address</dt>
            <dd className="break-words text-foreground">
              {store.address}
              {locality && <span className="block text-muted">{locality}</span>}
            </dd>
          </div>
        </div>

        <div className="flex gap-3">
          <PhoneIcon />
          <div className="min-w-0">
            <dt className="sr-only">Phone</dt>
            <dd>
              <a
                href={`tel:${store.phone}`}
                className="text-foreground underline-offset-4 hover:text-accent hover:underline"
              >
                {store.phone_display}
              </a>
              {store.phone_alt_display && (
                <a
                  href={`tel:${store.phone_alt}`}
                  className="block text-muted underline-offset-4 hover:text-accent hover:underline"
                >
                  {store.phone_alt_display}
                </a>
              )}
            </dd>
          </div>
        </div>

        {store.opening_hours && (
          <div className="flex gap-3">
            <ClockIcon />
            <div className="min-w-0">
              <dt className="sr-only">Opening hours</dt>
              <dd className="text-muted">{store.opening_hours}</dd>
            </div>
          </div>
        )}
      </dl>

      {/* `mt-auto` so every card in a row ends its actions on the same line however
          much address text sits above them. */}
      <div className="mt-auto flex flex-wrap gap-2 pt-6">
        <a
          href={`tel:${store.phone}`}
          className="inline-flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-medium text-surface transition hover:bg-accent-strong"
        >
          <PhoneIcon className="size-4 text-surface" />
          Call store
        </a>
        <a
          href={store.directions_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-full border border-line px-4 py-2 text-sm font-medium transition hover:border-accent hover:text-accent"
        >
          <PinIcon className="size-4" />
          Get directions
          <span className="sr-only">to {store.name} (opens in a new tab)</span>
        </a>
        {store.whatsapp_url && (
          <a
            href={store.whatsapp_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-full border border-line px-4 py-2 text-sm font-medium transition hover:border-accent hover:text-accent"
          >
            WhatsApp
            <span className="sr-only">{store.name} (opens in a new tab)</span>
          </a>
        )}
      </div>
    </article>
  );
}

/** Gold for our own counters, quiet green for the network. The distinction is the one
 *  thing on the card a customer scans for, so it is a colour AND a word — never colour
 *  alone, which says nothing to a screen reader or to a colour-blind reader. */
function StoreTypeBadge({ label, isToke }: { label: string; isToke: boolean }) {
  return (
    <span
      className={`shrink-0 rounded-full px-3 py-1 text-[0.6875rem] font-semibold uppercase tracking-[0.1em] ${
        isToke
          ? "bg-gold/15 text-[#8a6f10] ring-1 ring-gold/40"
          : "bg-accent/10 text-accent-strong ring-1 ring-accent/20"
      }`}
    >
      {label}
    </span>
  );
}

function PinIcon({ className = "size-4 shrink-0 text-accent" }: { className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 20 20" className={`mt-0.5 ${className}`} fill="none"
      stroke="currentColor" strokeWidth="1.5">
      <path d="M10 17.5s5.5-4.5 5.5-9a5.5 5.5 0 1 0-11 0c0 4.5 5.5 9 5.5 9Z"
        strokeLinejoin="round" />
      <circle cx="10" cy="8.5" r="2" />
    </svg>
  );
}

function PhoneIcon({ className = "size-4 shrink-0 text-accent" }: { className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 20 20" className={`mt-0.5 ${className}`} fill="none"
      stroke="currentColor" strokeWidth="1.5">
      <path
        d="M6.2 3h-.8A2.4 2.4 0 0 0 3 5.4C3 11.8 8.2 17 14.6 17A2.4 2.4 0 0 0 17 14.6v-.8a1 1 0 0 0-.7-1l-2.6-.8a1 1 0 0 0-1 .3l-.8.9a11.6 11.6 0 0 1-4.1-4.1l.9-.8a1 1 0 0 0 .3-1l-.8-2.6a1 1 0 0 0-1-.7Z"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ClockIcon({ className = "size-4 shrink-0 text-accent" }: { className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 20 20" className={`mt-0.5 ${className}`} fill="none"
      stroke="currentColor" strokeWidth="1.5">
      <circle cx="10" cy="10" r="7.5" />
      <path d="M10 5.5V10l3 1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
