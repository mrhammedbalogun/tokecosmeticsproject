"use client";
import { useEffect } from "react";

/** Sets data-scrolled on <html> past 24px; globals.css shrinks the header. Renders
 * nothing — the header itself stays a Server Component. */
export function ScrollShrink() {
  useEffect(() => {
    const onScroll = () =>
      document.documentElement.toggleAttribute("data-scrolled", window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return null;
}
