"use client";
import Image from "next/image";
import { useSyncExternalStore } from "react";

/**
 * The product card's second artwork — the one that fades in under the cursor.
 *
 * ── WHY IT IS A COMPONENT AND NOT TWO TAILWIND CLASSES ──────────────────────────────
 *
 * It used to sit in `ProductCard` as a plain `<Image>` carrying `opacity-0
 * group-hover:opacity-100`. Opacity is not display: the element was laid out, so every
 * browser lazy-loaded it the moment the card scrolled into view — on phones too, where
 * there is no cursor and the image can never be seen. On `/products` that is one extra
 * optimised image per card with a hover state nobody can reach.
 *
 * `hidden md:block` would not have fixed it. A breakpoint is a guess about screen width,
 * not about input device, and a `display:none` image is only *usually* skipped — the
 * spec does not promise it and the srcset candidates still resolve. This asks the real
 * question instead: `(hover: hover)`, i.e. can the primary input hover at all. False on
 * a phone or tablet, true on a laptop, and correct on a touchscreen laptop where the
 * mouse is still the primary input.
 *
 * ── HYDRATION ───────────────────────────────────────────────────────────────────────
 *
 * The server snapshot is `false`, so the server emits nothing and React's hydration pass
 * renders nothing — identical trees, no mismatch. Only afterwards does React re-read the
 * live snapshot and mount the image on a hover-capable device. Same primitive as
 * `Motion.tsx::useHydrated` and `HeroSlider`'s reduced-motion read.
 *
 * ── WHY THE CARD'S OWN CLASSES NEEDED NO CHANGE ─────────────────────────────────────
 *
 * The primary image keeps `group-hover:opacity-0`, and on touch that rule is dead
 * anyway: Tailwind v4 emits every `group-hover:` utility inside `@media (hover: hover)`
 * (verified in the built CSS). So a phone cannot fade the primary out and find nothing
 * behind it — the swap is off at both layers, independently.
 */
const HOVER_QUERY = "(hover: hover)";

function subscribe(onChange: () => void): () => void {
  const list = window.matchMedia(HOVER_QUERY);
  list.addEventListener("change", onChange);
  return () => list.removeEventListener("change", onChange);
}

export function CardHoverImage({ src, sizes }: { src: string; sizes: string }) {
  const canHover = useSyncExternalStore(
    subscribe,
    () => window.matchMedia(HOVER_QUERY).matches,
    () => false,
  );
  if (!canHover) return null;

  // Byte-for-byte the markup ProductCard used to render inline — same alt, aria-hidden,
  // fill, sizes and classes — so desktop hover is unchanged in look and timing.
  return (
    <Image
      src={src}
      alt=""
      aria-hidden
      fill
      sizes={sizes}
      className="object-cover opacity-0 transition-all duration-500 ease-out group-hover:scale-[1.04] group-hover:opacity-100"
    />
  );
}
