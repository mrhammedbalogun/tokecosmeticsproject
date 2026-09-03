import Image from "next/image";
import Link from "next/link";
import type { ComboContentItem } from "@/lib/combos";
import { formatMoney } from "@/lib/country";
import { mediaUrl } from "@/lib/media";

/**
 * What is in the box, laid out as the shopper would inspect it on a counter.
 *
 * ── THE SELECTED OPTIONS ARE NAMED, NOT SUMMARISED ──────────────────────────────────
 *
 * `option_values` arrives as {"Size": "500g", "Pricing option": "Pieces"} and is rendered
 * as labelled chips rather than joined into a string. "500g · Pieces" is ambiguous the
 * moment a product has two axes; "Size 500g" and "Pricing option Pieces" are not, and
 * this is precisely the question — *which* one is in the box — that a bundle page exists
 * to answer.
 *
 * ── EVERY ROW LINKS TO ITS OWN PRODUCT PAGE ─────────────────────────────────────────
 *
 * The strike-through price on the buy panel is a claim, and a claim a shopper can check
 * is worth more than one they cannot. The link is also how somebody who wants only the
 * cleanser finds it.
 */
export function ComboContents({
  items,
  currency,
}: {
  items: ComboContentItem[];
  currency: string;
}) {
  return (
    <ul className="grid gap-4 sm:grid-cols-2">
      {items.map((item) => {
        const img = mediaUrl(item.image);
        const options = Object.entries(item.option_values ?? {}).filter(([, v]) => v);
        return (
          <li key={item.sku}>
            <Link
              href={`/product/${item.product_slug}`}
              className="group flex h-full gap-4 rounded-[var(--radius-card)] border border-line/60 bg-surface p-4 transition-all duration-300 hover:-translate-y-0.5 hover:border-line hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <div className="relative h-24 w-24 shrink-0 overflow-hidden rounded-lg bg-beige">
                {img && (
                  <Image
                    src={img}
                    alt={item.product_name}
                    fill
                    sizes="96px"
                    className="object-cover transition-transform duration-500 group-hover:scale-[1.05]"
                  />
                )}
                {item.quantity > 1 && (
                  <span className="absolute right-1 top-1 rounded-full bg-foreground/85 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                    ×{item.quantity}
                  </span>
                )}
              </div>

              <div className="min-w-0 flex-1">
                <h3 className="font-medium leading-snug">{item.product_name}</h3>

                {options.length > 0 && (
                  <ul className="mt-1.5 flex flex-wrap gap-1.5">
                    {options.map(([label, value]) => (
                      <li
                        key={label}
                        className="rounded-full border border-line bg-background px-2 py-0.5 text-[11px]"
                      >
                        <span className="text-muted">{label}</span>{" "}
                        <span className="font-medium">{value}</span>
                      </li>
                    ))}
                  </ul>
                )}

                {item.short_description && (
                  <p
                    className="mt-1.5 line-clamp-2 text-xs text-muted [&_p]:inline"
                    // The API returns nh3-sanitised HTML for this field, the same as the
                    // PDP renders — stripping tags here would drop the author's emphasis.
                    dangerouslySetInnerHTML={{ __html: item.short_description }}
                  />
                )}

                <p className="mt-2 text-sm">
                  {item.line_total ? (
                    <>
                      <span className="text-muted">Worth </span>
                      <span className="font-medium">
                        {formatMoney(item.line_total, currency)}
                      </span>
                      {item.quantity > 1 && item.unit_price && (
                        <span className="text-muted">
                          {" "}
                          ({item.quantity} × {formatMoney(item.unit_price, currency)})
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="text-muted">
                      {item.quantity} × {item.variant_name}
                    </span>
                  )}
                </p>
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
