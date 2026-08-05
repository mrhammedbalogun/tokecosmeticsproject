"use client";
import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Full-screen overlays (cart drawer, mobile nav) are mounted inside the header,
 * whose backdrop-blur makes it the containing block for position:fixed — clipping
 * them to the header strip. Portaling to <body> keeps fixed viewport-relative.
 * Renders nothing on the server; overlays are interactive-only UI. */
export function OverlayPortal({ children }: { children: ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;
  return createPortal(children, document.body);
}
