import Image from "next/image";
import Link from "next/link";
import { EDUCATION } from "@/lib/home-content";
import { FadeUp } from "@/components/motion/Motion";

/** Section 13: "The skincare journal" — editorial article teasers (D3 content;
 * links point at /page/blog until the Plan-19 blog ships). Calm image zoom on
 * hover, article title as the accessible link name. Lazy images (below the fold). */
export function EducationTeasers() {
  return (
    <section aria-labelledby="edu-h" className="mx-auto max-w-7xl px-4 py-16">
      <FadeUp>
        <h2 id="edu-h" className="font-display text-3xl md:text-4xl">
          The skincare journal
        </h2>
      </FadeUp>
      <div className="mt-8 grid gap-4 md:grid-cols-3">
        {EDUCATION.map((a, i) => (
          <FadeUp key={a.title} delay={i * 0.06}>
            <Link
              href={a.href}
              className="group block rounded-[var(--radius-card)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <div className="overflow-hidden rounded-[var(--radius-card)]">
                <Image
                  src={a.image}
                  alt=""
                  width={1200}
                  height={700}
                  className="aspect-[16/10] w-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.02]"
                  loading="lazy"
                />
              </div>
              <h3 className="mt-4 font-display text-lg transition-colors group-hover:text-accent">
                {a.title}
              </h3>
            </Link>
          </FadeUp>
        ))}
      </div>
    </section>
  );
}
