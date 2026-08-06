"use client";
import { useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Full-screen overlays (cart drawer, mobile nav) are mounted inside the header,
 * whose backdrop-blur makes it the containing block for position:fixed — clipping
 * them to the header strip. Portaling to <body> keeps fixed viewport-relative.
 * Renders nothing on the server; overlays are interactive-only UI. */

// "Am I on the client?" as external state: the server snapshot answers no, the client
// snapshot yes, and nothing ever changes after that — hence the no-op subscribe.
const emptySubscribe = () => () => {};

export function OverlayPortal({ children }: { children: ReactNode }) {
  const mounted = useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false,
  );
  if (!mounted) return null;
  return createPortal(children, document.body);
}
