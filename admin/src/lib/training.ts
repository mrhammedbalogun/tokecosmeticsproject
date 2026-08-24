/**
 * The staff training library (2026-08-23): types and the YouTube URL builders.
 *
 * EVERYTHING RENDERED IS BUILT FROM `video_id`, an 11-character id the backend
 * derived and validated (`backend/apps/cms/youtube.py`). The player iframe and the
 * thumbnail never interpolate a pasted URL — only the id into a fixed origin — so a
 * hostile link cannot become a hostile `src`. CSP's `frame-src`/`img-src` pin the
 * two origins as the second fence (`src/lib/csp.ts`).
 */

export interface TrainingRow {
  id: number;
  title: string;
  description: string;
  youtube_url: string;
  video_id: string;
  position: number;
  /** Absent from the staff library endpoint, whose rows are all published. */
  is_published?: boolean;
  created_at: string;
  updated_at?: string;
}

/** Privacy-enhanced embed: no YouTube cookies until the viewer actually plays.
 *  `autoplay=1` because the iframe only exists after a click on the thumbnail —
 *  without it that click would be followed by a second click on YouTube's own
 *  play button. `rel=0` keeps end-of-video suggestions to the same channel. */
export function trainingEmbedUrl(videoId: string): string {
  return `https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&rel=0`;
}

/** The click-to-play poster. `hqdefault` exists for every video (the larger
 *  `maxresdefault` 404s on older uploads, which would blank the card). */
export function trainingThumbnailUrl(videoId: string): string {
  return `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`;
}

/**
 * CLIENT-SIDE MIRROR of the backend parser, for instant feedback only: it powers
 * the live preview in the form and a friendlier pre-check message. The backend
 * re-derives from scratch and is the authority — a link this mirror likes can
 * still be refused, and the form must render that refusal.
 */
export function parseYoutubeVideoId(raw: string): string | null {
  const ID = /^[A-Za-z0-9_-]{11}$/;
  const HOSTS = new Set([
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "youtu.be",
  ]);
  let text = (raw ?? "").trim();
  if (!text) return null;
  if (!text.includes("://")) text = `https://${text}`;

  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  if (!HOSTS.has(url.hostname.toLowerCase())) return null;

  const segments = url.pathname.split("/").filter(Boolean);
  if (url.hostname.toLowerCase() === "youtu.be") {
    const candidate = segments[0] ?? "";
    return ID.test(candidate) ? candidate : null;
  }
  if (segments[0] === "watch") {
    const candidate = url.searchParams.get("v") ?? "";
    return ID.test(candidate) ? candidate : null;
  }
  if (segments.length >= 2 && ["shorts", "embed", "live", "v"].includes(segments[0])) {
    return ID.test(segments[1]) ? segments[1] : null;
  }
  return null;
}
