import { describe, it, expect } from "vitest";
import {
  parseYoutubeVideoId,
  trainingEmbedUrl,
  trainingThumbnailUrl,
} from "@/lib/training";

// The client parser is a MIRROR of backend/apps/cms/youtube.py, for instant form
// feedback only — the backend re-derives and is the authority. These cases are copied
// from apps/cms/tests/test_training.py so a drift between the two shows up as a
// failure here rather than as a form that says "looks fine" about a link the API
// then refuses.
const VID = "dQw4w9WgXcQ";

describe("parseYoutubeVideoId accepts every real link shape", () => {
  it.each([
    `https://www.youtube.com/watch?v=${VID}`,
    `https://m.youtube.com/watch?v=${VID}&list=PLx&index=2`,
    `https://www.youtube.com/watch?t=42&v=${VID}`,
    `https://youtu.be/${VID}`,
    `https://youtu.be/${VID}?si=SHARETRACKING&t=90`,
    `youtu.be/${VID}`,
    `www.youtube.com/watch?v=${VID}`,
    `https://www.youtube.com/shorts/${VID}`,
    `https://www.youtube.com/embed/${VID}`,
    `https://www.youtube.com/live/${VID}`,
  ])("%s", (url) => {
    expect(parseYoutubeVideoId(url)).toBe(VID);
  });
});

describe("parseYoutubeVideoId refuses a link that names no video", () => {
  it.each([
    "",
    "not a url",
    "https://vimeo.com/12345678",
    `https://notyoutube.com/watch?v=${VID}`,
    `https://youtube.com.evil.example/watch?v=${VID}`,
    "https://www.youtube.com/",
    "https://www.youtube.com/@TokeCosmetics",
    "https://www.youtube.com/playlist?list=PLx",
    "https://www.youtube.com/watch?v=tooshort",
    "javascript:alert(1)",
  ])("%s", (url) => {
    expect(parseYoutubeVideoId(url)).toBeNull();
  });
});

describe("the player and poster URLs are built from the id, never a pasted URL", () => {
  it("embeds via the privacy-enhanced origin", () => {
    expect(trainingEmbedUrl(VID)).toBe(
      `https://www.youtube-nocookie.com/embed/${VID}?autoplay=1&rel=0`,
    );
  });
  it("posters via i.ytimg.com's always-present size", () => {
    expect(trainingThumbnailUrl(VID)).toBe(`https://i.ytimg.com/vi/${VID}/hqdefault.jpg`);
  });
});
