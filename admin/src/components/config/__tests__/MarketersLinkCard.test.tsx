import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MarketersLinkCard } from "@/components/config/MarketersLinkCard";

describe("MarketersLinkCard", () => {
  it("shows the absolute /partner/rates URL for the current host", () => {
    render(<MarketersLinkCard />);
    // jsdom's origin is http://localhost:3000 — the point is origin + fixed path.
    expect(
      screen.getByText(`${window.location.origin}/partner/rates`),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open/i })).toHaveAttribute(
      "href",
      "/partner/rates",
    );
  });

  it("copies the full URL to the clipboard and confirms", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<MarketersLinkCard />);
    fireEvent.click(screen.getByRole("button", { name: /copy link/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /copied/i })).toBeInTheDocument(),
    );
    expect(writeText).toHaveBeenCalledWith(
      `${window.location.origin}/partner/rates`,
    );
  });
});
