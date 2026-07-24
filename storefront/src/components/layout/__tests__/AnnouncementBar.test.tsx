import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { AnnouncementBar } from "@/components/layout/AnnouncementBar";
import { ANNOUNCEMENTS } from "@/lib/home-content";

// Rotation only runs when reduced-motion is NOT requested; jsdom has no
// matchMedia, so stub it to report "motion allowed".
beforeEach(() => {
  vi.useFakeTimers();
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  }) as any;
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("AnnouncementBar", () => {
  it("renders the first message on mount (SSR-stable, no CLS)", () => {
    render(<AnnouncementBar />);
    expect(screen.getByText(ANNOUNCEMENTS[0])).toBeInTheDocument();
  });

  it("advances one message per 5s tick and wraps the index back to 0", () => {
    render(<AnnouncementBar />);
    for (let n = 1; n < ANNOUNCEMENTS.length; n++) {
      act(() => {
        vi.advanceTimersByTime(5000);
      });
      expect(screen.getByText(ANNOUNCEMENTS[n])).toBeInTheDocument();
    }
    // One more tick past the last message wraps to index 0 (modulo length).
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByText(ANNOUNCEMENTS[0])).toBeInTheDocument();
  });

  it("stays on the first message when reduced motion is requested", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window.matchMedia as any).mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });
    render(<AnnouncementBar />);
    act(() => {
      vi.advanceTimersByTime(20000);
    });
    expect(screen.getByText(ANNOUNCEMENTS[0])).toBeInTheDocument();
  });
});
