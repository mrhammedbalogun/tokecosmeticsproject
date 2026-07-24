"use client";
/** The ONLY entry point for framer-motion in the storefront. `m` + LazyMotion
 * with the `domAnimation` feature bundle (~half the weight of the full `motion`
 * feature set) is the Lighthouse-friendly pairing. Note: `domAnimation` is a
 * static import, so it ships in the shared Providers bundle (loaded site-wide) —
 * it is NOT lazily fetched per-island; the saving is the smaller feature set,
 * not deferral. Every effect respects prefers-reduced-motion. Vocabulary
 * (design-direction.md): fade-up on scroll, subtle hover lift/zoom — calm and
 * expensive, never busy. */
import { LazyMotion, domAnimation, m, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";

export function MotionRoot({ children }: { children: ReactNode }) {
  return (
    <LazyMotion features={domAnimation} strict>
      {children}
    </LazyMotion>
  );
}

export function FadeUp({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduced = useReducedMotion();
  if (reduced) return <div className={className}>{children}</div>;
  return (
    <m.div
      className={className}
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.55, delay, ease: [0.21, 0.61, 0.35, 1] }}
    >
      {children}
    </m.div>
  );
}
