import { NewsletterForm } from "@/components/layout/NewsletterForm";
import { FadeUp } from "@/components/motion/Motion";

/** Section 14: newsletter CTA — minimal, elegant, on the forest-green band. Reuses
 * the Plan-12 NewsletterForm via its `onAccent` variant (no duplicated form logic)
 * so the button/input stay legible against the green. */
export function NewsletterCta() {
  return (
    <section aria-labelledby="nl-h" className="bg-accent">
      <FadeUp>
        <div className="mx-auto max-w-2xl px-4 py-16 text-center text-surface">
          <h2 id="nl-h" className="font-display text-3xl md:text-4xl">
            Glow, delivered.
          </h2>
          <p className="mt-3 text-surface/85">
            Skincare science, launches and members-only offers. No spam, ever.
          </p>
          <div className="mt-6">
            <NewsletterForm variant="onAccent" />
          </div>
        </div>
      </FadeUp>
    </section>
  );
}
