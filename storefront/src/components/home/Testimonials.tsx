import Image from "next/image";
import { TESTIMONIALS } from "@/lib/home-content";
import { Carousel } from "@/components/home/Carousel";
import { FadeUp } from "@/components/motion/Motion";

/** Section 11: "Loved worldwide" — premium testimonial carousel with avatars (D3
 * content). Server shell renders the figures; the horizontal scroll-snap Carousel
 * is the only client island. Gold stars are the seasoning accent; avatars use
 * alt="" because the name is in the caption text beside them. */
export function Testimonials() {
  return (
    <section aria-labelledby="reviews-h" className="mx-auto max-w-7xl px-4 py-16">
      <FadeUp>
        <h2 id="reviews-h" className="font-display text-3xl md:text-4xl">
          Loved worldwide
        </h2>
      </FadeUp>
      <div className="mt-8">
        <Carousel label="Customer reviews">
          {TESTIMONIALS.map((t) => (
            <figure
              key={t.name}
              className="w-[85vw] shrink-0 snap-start rounded-[var(--radius-card)] bg-surface p-8 shadow-sm sm:w-[420px]"
            >
              <div aria-hidden className="tracking-widest text-gold">
                ★★★★★
              </div>
              <blockquote className="mt-4 font-display text-lg leading-relaxed">
                “{t.quote}”
              </blockquote>
              <figcaption className="mt-5 flex items-center gap-3 text-sm text-muted">
                <Image
                  src={t.avatar}
                  alt=""
                  width={40}
                  height={40}
                  className="h-10 w-10 rounded-full object-cover"
                />
                <span>
                  {t.name} · {t.where}
                </span>
              </figcaption>
            </figure>
          ))}
        </Carousel>
      </div>
    </section>
  );
}
