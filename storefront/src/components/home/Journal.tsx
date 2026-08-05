import Link from "next/link";
import { FadeUp } from "@/components/motion/Motion";

/** Artifact section: three beige journal teasers. Links go to the blog landing
 * (a coming-soon page until Plan-31 builds the blog). */
const POSTS = [
  { eyebrow: "Routine", title: "3 morning skincare steps for a healthy glow",
    text: "Kickstart your day with a simple, effective routine that wakes up your skin and keeps it radiant from morning to night." },
  { eyebrow: "Ingredients", title: "Ingredients to avoid in your skincare routine",
    text: "Not all products are created equal — learn which common ingredients can irritate or age your skin, and what to choose instead." },
  { eyebrow: "Science", title: "Why hydration is the secret to youthful skin",
    text: "How proper hydration can plump fine lines, improve elasticity and transform dull, tired skin into a fresh, healthy complexion." },
];

export function Journal() {
  return (
    <section aria-label="The Journal" className="wrap py-8">
      <FadeUp>
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted">The Journal</p>
        <h2 className="mt-1 font-display text-3xl md:text-4xl">Skincare, explained simply</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {POSTS.map((post) => (
            <article key={post.title} className="rounded-[var(--radius-card)] bg-beige p-6">
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted">
                {post.eyebrow}
              </p>
              <h3 className="mt-2 font-display text-lg leading-snug">{post.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{post.text}</p>
              <Link
                href="/blog"
                className="mt-4 inline-block text-xs font-semibold uppercase tracking-[0.08em] text-accent hover:text-accent-strong"
              >
                Read →
              </Link>
            </article>
          ))}
        </div>
      </FadeUp>
    </section>
  );
}
