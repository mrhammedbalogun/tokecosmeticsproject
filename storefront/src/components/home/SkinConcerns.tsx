import Image from "next/image";
import Link from "next/link";
import { SKIN_CONCERNS } from "@/lib/home-content";
import { FadeUp } from "@/components/motion/Motion";

/** Section 5: shop by skin concern. Static tiles (D3 content) that deep-link into
 * `/products?tag=…` PLPs. The `#skin-concerns` id is the hero "Take Skin Quiz"
 * anchor target until a real quiz exists. Warm-beige band separates it from the
 * cream sections above and below for editorial rhythm. */
export function SkinConcerns() {
  return (
    <section id="skin-concerns" aria-labelledby="concerns-h" className="scroll-mt-24 bg-beige">
      <div className="mx-auto max-w-7xl px-4 py-20">
        <FadeUp className="max-w-2xl">
          <p className="flex items-center gap-3 text-xs font-medium uppercase tracking-[0.22em] text-accent">
            <span className="h-px w-8 bg-gold" aria-hidden />
            Targeted care
          </p>
          <h2 id="concerns-h" className="mt-4 font-display text-3xl md:text-4xl">
            Shop by skin concern
          </h2>
          <p className="mt-3 leading-relaxed text-muted">
            Tell us what your skin needs — we will point you to the right ritual.
          </p>
        </FadeUp>
        <div className="mt-12 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {SKIN_CONCERNS.map((c, i) => (
            <FadeUp key={c.slug} delay={i * 0.04}>
              <Link
                href={c.href}
                className="group relative block overflow-hidden rounded-[var(--radius-card)] shadow-sm transition-shadow duration-300 hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <Image
                  src={c.image}
                  alt=""
                  width={600}
                  height={600}
                  className="aspect-square w-full object-cover transition-transform duration-500 group-hover:scale-105"
                />
                <span className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/60 via-black/25 to-transparent p-4 font-medium text-surface">
                  {c.name}
                  <span
                    aria-hidden
                    className="translate-x-0 opacity-70 transition-all duration-300 group-hover:translate-x-1 group-hover:opacity-100"
                  >
                    →
                  </span>
                </span>
              </Link>
            </FadeUp>
          ))}
        </div>
      </div>
    </section>
  );
}
