import Image from "next/image";
import Link from "next/link";
import type { ComboCard as ComboCardData } from "@/lib/combos";
import { ComboSavingBadge } from "@/components/combo/ComboSavingBadge";
import { formatMoney } from "@/lib/country";
import { mediaUrl } from "@/lib/media";

/**
 * The combo card.
 *
 * ── IT SHOWS WHAT IS IN THE BOX, NOT JUST THE BOX ───────────────────────────────────
 *
 * A bundle card carrying only its own hero photograph tells a shopper nothing about what
 * they would be buying — which is the ONE question a bundle has to answer before it is
 * clicked. So the component pictures ride along the bottom as a small stack, and the
 * count is stated in words. Where a combo has no hero image of its own, the stack becomes
 * the artwork rather than leaving an empty frame.
 *
 * The motion vocabulary is the product card's, deliberately: lift, gentle zoom, no
 * bounce. Two card shapes on one site should feel like one shop.
 */
export function ComboCard({
  combo,
  priority = false,
}: {
  combo: ComboCardData;
  priority?: boolean;
}) {
  const hero = mediaUrl(combo.image);
  const thumbs = combo.item_images.map(mediaUrl).filter((u): u is string => Boolean(u));

  return (
    <Link
      href={`/combo/${combo.slug}`}
      className="group block overflow-hidden rounded-[var(--radius-card)] border border-line/60 bg-surface shadow-sm transition-all duration-300 ease-out hover:-translate-y-1 hover:border-line hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <div className="relative aspect-[4/3] overflow-hidden bg-beige">
        {hero ? (
          <Image
            src={hero}
            alt={combo.name}
            fill
            priority={priority}
            sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw"
            className="object-cover transition-transform duration-500 ease-out group-hover:scale-[1.04]"
          />
        ) : (
          <div className="flex h-full items-center justify-center gap-2 p-6">
            {thumbs.slice(0, 3).map((src, i) => (
              <span
                key={`${src}-${i}`}
                className="relative h-20 w-20 overflow-hidden rounded-full border-2 border-surface bg-surface shadow-sm"
              >
                <Image src={src} alt="" fill sizes="80px" className="object-cover" />
              </span>
            ))}
          </div>
        )}

        {combo.pricing && (
          <span className="absolute left-3 top-3">
            <ComboSavingBadge pricing={combo.pricing} size="sm" />
          </span>
        )}
        {!combo.in_stock && (
          <span className="absolute right-3 top-3 rounded-full bg-surface/95 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted">
            Sold Out
          </span>
        )}

        {hero && thumbs.length > 0 && (
          <div className="absolute inset-x-0 bottom-0 flex items-end gap-1.5 bg-gradient-to-t from-black/45 to-transparent p-3">
            {thumbs.map((src, i) => (
              <span
                // NOT keyed on the URL alone: two variants of one product fall back to
                // that product's first picture, so the same URL legitimately appears
                // twice in this strip.
                key={`${src}-${i}`}
                className="relative h-9 w-9 shrink-0 overflow-hidden rounded-full border-2 border-white/90 bg-surface"
              >
                <Image src={src} alt="" fill sizes="36px" className="object-cover" />
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="p-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
          {combo.item_count} {combo.item_count === 1 ? "product" : "products"} in one box
        </p>
        <h3 className="mt-1 font-display text-lg leading-snug">{combo.name}</h3>
        {combo.short_description && (
          <p className="mt-1 line-clamp-2 text-sm text-muted">{combo.short_description}</p>
        )}

        {combo.pricing && (
          <div className="mt-3 flex flex-wrap items-baseline gap-2">
            <span className="text-xl font-medium">
              {formatMoney(combo.pricing.amount, combo.pricing.currency)}
            </span>
            <s className="text-sm text-muted">
              {formatMoney(combo.pricing.components_total, combo.pricing.currency)}
            </s>
          </div>
        )}

        <span className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-accent">
          See what&rsquo;s inside
          <span
            aria-hidden="true"
            className="transition-transform duration-300 group-hover:translate-x-0.5"
          >
            →
          </span>
        </span>
      </div>
    </Link>
  );
}
