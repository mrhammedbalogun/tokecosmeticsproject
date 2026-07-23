import Image from "next/image";
import { COMMUNITY } from "@/lib/home-content";
import { FadeUp } from "@/components/motion/Motion";

/** Section 12: "#TokeGlow community" — Instagram/UGC masonry (D3 content). CSS
 * `columns` gives the masonry flow with zero JS and zero layout-shift risk;
 * `break-inside-avoid` keeps each tile whole. Alternating tile heights read as an
 * editorial mosaic. Images are lazy (below the fold) and carry real alt text. */
export function CommunityGrid() {
  return (
    <section aria-labelledby="community-h" className="bg-beige">
      <div className="mx-auto max-w-7xl px-4 py-16">
        <FadeUp>
          <h2 id="community-h" className="font-display text-3xl md:text-4xl">
            #TokeGlow community
          </h2>
          <p className="mt-2 text-muted">
            Real routines from Lagos to London — tag us to be featured.
          </p>
        </FadeUp>
        <div className="mt-8 columns-2 gap-4 md:columns-3 [&>*]:mb-4">
          {COMMUNITY.map((c, i) => (
            <Image
              key={i}
              src={c.image}
              alt={c.alt}
              width={700}
              height={i % 2 ? 900 : 700}
              className="w-full break-inside-avoid rounded-[var(--radius-card)]"
              loading="lazy"
            />
          ))}
        </div>
      </div>
    </section>
  );
}
