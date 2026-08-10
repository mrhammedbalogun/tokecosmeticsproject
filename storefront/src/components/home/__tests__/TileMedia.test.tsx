import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TileMedia } from "@/components/home/TileMedia";
import type { CmsBanner } from "@/lib/cms";

const base: Omit<CmsBanner, "video_url" | "video_mode" | "image"> = {
  id: 1,
  placement: "hero",
  sort: 0,
  title: "",
  subtitle: "",
  tagline: "",
  cta_text: "",
  cta_url: "",
  mobile_image: null,
};

describe("TileMedia video modes", () => {
  it("loop mode autoplays but no longer preloads the whole file", () => {
    const { container } = render(
      <TileMedia
        tone="x"
        banner={{ ...base, image: null, video_url: "https://cdn/x.mp4", video_mode: "loop" }}
      />,
    );
    const video = container.querySelector("video")!;
    expect(video).toHaveAttribute("autoplay");
    expect(video).toHaveAttribute("loop");
    expect(video).toHaveAttribute("preload", "metadata");
  });

  it("click mode renders NO video element until the visitor asks for one", () => {
    const { container } = render(
      <TileMedia
        tone="x"
        banner={{
          ...base,
          video_url: "https://cdn/x.mp4",
          video_mode: "click",
          image: "https://cdn/p.jpg",
        }}
      />,
    );
    expect(container.querySelector("video")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /play/i }));
    expect(container.querySelector("video")).not.toBeNull();
  });
});
