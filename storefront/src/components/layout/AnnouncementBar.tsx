import Link from "next/link";
import type { AnnouncementItem } from "@/lib/cms";
import { ANNOUNCEMENTS } from "@/lib/home-content";

/** Section 1: the news MARQUEE (landing redesign, approved 2026-08-04).
 *
 * Items scroll continuously right-to-left in a seamless loop — the track is
 * rendered twice and translated -50%, so the wrap point is invisible. Hover
 * pauses it so an item can be read or clicked; items with a URL are links.
 * Pure CSS animation (keyframes in globals.css): zero JS shipped, and
 * `prefers-reduced-motion` degrades to a static centred first item. Server
 * Component now — the old rotating version was this layout's only forced island.
 *
 * Items come from CMS strip banners (title + optional cta_url); the Plan-13
 * fixtures keep the bar alive when the CMS is empty or down.
 */
export function AnnouncementBar(
  { items, pending = false }: { items?: AnnouncementItem[]; pending?: boolean } = {},
) {
  /**
   * `pending` — the answer is on its way, so show the BAR but none of its words.
   *
   * Only a prerendered page passes it. The fallback below is the right answer when the
   * CMS is empty or down, but it is the wrong answer before anybody has asked: the first
   * fixture reads "Free delivery in Nigeria on orders over ₦50,000", and baking that into
   * HTML that is served to every market is precisely the wrong-country content that
   * `(static-shop)` exists to avoid. The strip keeps its `min-h-9`, so filling it in a
   * moment later moves nothing on the page.
   */
  const news = pending
    ? []
    : items?.length ? items : ANNOUNCEMENTS.map((text) => ({ text, url: "" }));
  // Two copies of the list = one seamless loop.
  const track = [...news, ...news];
  return (
    <div
      className="announce-marquee min-h-9 overflow-hidden border-b border-accent-strong/40 bg-accent text-surface"
      aria-live="off"
    >
      <div className="announce-track flex w-max items-center py-2">
        {track.map((item, i) => (
          <span
            key={i}
            aria-hidden={i >= news.length}
            className="flex items-center whitespace-nowrap px-7 text-xs font-medium tracking-[0.08em]"
          >
            {item.url ? (
              <Link href={item.url} className="underline-offset-2 hover:underline">
                {item.text}
              </Link>
            ) : (
              item.text
            )}
            <span aria-hidden className="ml-14 text-[9px] text-leaf">
              ✦
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
