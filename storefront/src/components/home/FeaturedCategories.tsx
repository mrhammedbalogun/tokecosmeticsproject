import Image from "next/image";
import Link from "next/link";
import type { CategoryNode } from "@/lib/catalog";
import { mediaUrl } from "@/lib/media";
import { FadeUp } from "@/components/motion/Motion";

/** Section 4: featured categories. Data is the live category tree (Task 3), so the
 * cards always match the real catalog. Circular editorial tiles with a calm hover
 * zoom + label colour shift. Falls back to a warm-beige disc if a category has no
 * seeded image, so the grid never breaks. */
export function FeaturedCategories({ categories }: { categories: CategoryNode[] }) {
  const roots = categories.slice(0, 6);
  if (roots.length === 0) return null;
  return (
    <section aria-labelledby="cats-h" className="mx-auto max-w-7xl px-4 py-20">
      <FadeUp className="max-w-2xl">
        <p className="flex items-center gap-3 text-xs font-medium uppercase tracking-[0.22em] text-accent">
          <span className="h-px w-8 bg-gold" aria-hidden />
          Explore the range
        </p>
        <h2 id="cats-h" className="mt-4 font-display text-3xl md:text-4xl">
          Shop by category
        </h2>
        <p className="mt-3 leading-relaxed text-muted">
          From face to family — curated rituals for every skin, every age.
        </p>
      </FadeUp>
      <div className="mt-12 grid grid-cols-2 gap-x-4 gap-y-8 md:grid-cols-3 lg:grid-cols-6">
        {roots.map((c, i) => (
          <FadeUp key={c.slug} delay={i * 0.05}>
            <Link
              href={`/category/${c.slug}`}
              className="group block rounded-[var(--radius-card)] text-center focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
            >
              <div className="relative aspect-square overflow-hidden rounded-full bg-beige shadow-sm ring-1 ring-line/60 transition-shadow duration-300 group-hover:shadow-md">
                {mediaUrl(c.image) && (
                  <Image
                    src={mediaUrl(c.image)!}
                    alt=""
                    fill
                    sizes="(max-width:768px) 45vw, 15vw"
                    className="object-cover transition-transform duration-500 group-hover:scale-105"
                  />
                )}
              </div>
              <p className="mt-4 text-sm font-medium transition-colors group-hover:text-accent">
                {c.name}
              </p>
            </Link>
          </FadeUp>
        ))}
      </div>
    </section>
  );
}
