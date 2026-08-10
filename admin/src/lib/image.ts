/**
 * Client-side image downscaling, applied before an upload leaves the browser.
 *
 * Two ceilings make this necessary, and neither is ours to raise: Next server actions
 * cap the request body (next.config.ts sets 85mb for self-hosting), but Vercel caps
 * function request bodies at ~4.5MB at the platform edge — a phone photo is routinely
 * 3–12MB, so without this step "upload a photo" simply does not work in production.
 * It is also the right thing for the storefront: these files are served to customers
 * as-is from CloudFront, and no homepage tile needs a 4000px original.
 *
 * The contract callers rely on (2026-08-08 rework, after a PNG sailed past the old
 * single-pass downscale and died at the Vercel edge): the result is under
 * UPLOAD_CAP_BYTES whenever the browser can decode the file at all. PNG is tried
 * losslessly first (alpha survives); if that is still too big the encode ladder walks
 * WebP (alpha survives) and then white-matted JPEG at shrinking quality/size until one
 * fits. GIF and SVG pass through untouched — re-encoding would destroy animation /
 * scalability — as does anything the browser cannot decode (e.g. HEIC outside Safari),
 * so callers MUST still check the returned file against UPLOAD_CAP_BYTES and refuse to
 * send an oversized one: a friendly sentence beats a request the platform kills.
 */

/** Longest edge after downscaling; comfortably above any homepage render size. */
const MAX_EDGE = 2560;

/** Files at or under this size skip the round-trip — they already upload fine. */
const SKIP_UNDER_BYTES = 1_500_000;

/**
 * The real-world upload ceiling: Vercel rejects function request bodies at ~4.5MB
 * before Next runs, and multipart framing adds overhead — 4MB leaves honest headroom.
 * Every upload call site checks staged files against this and refuses early, because a
 * request over it never reaches the server to be refused politely.
 */
export const UPLOAD_CAP_BYTES = 4_000_000;

/** "12.4 MB" — for the refusal sentences the call sites show. */
export function fileSizeMb(file: File): string {
  return `${(file.size / 1_000_000).toFixed(1)} MB`;
}

/** One canvas encode. Returns null when the browser cannot honour `type` (Safari
 * answers a WebP request with PNG — the blob's actual type gives it away). */
async function encodeScaled(
  bitmap: ImageBitmap,
  edge: number,
  type: string,
  quality: number | undefined,
): Promise<Blob | null> {
  const scale = Math.min(1, edge / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  if (type === "image/jpeg") {
    // JPEG has no alpha; without a matte, transparent pixels encode as black.
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, type, quality));
  return blob && blob.type === type ? blob : null;
}

const EXT: Record<string, string> = {
  "image/png": ".png",
  "image/webp": ".webp",
  "image/jpeg": ".jpg",
};

function toFile(blob: Blob, name: string): File {
  return new File([blob], name.replace(/\.\w+$/, "") + EXT[blob.type], { type: blob.type });
}

export async function downscaleImage(file: File): Promise<File> {
  if (!file.type.startsWith("image/")) return file;
  if (file.type === "image/gif" || file.type === "image/svg+xml") return file;
  if (file.size <= SKIP_UNDER_BYTES) return file;

  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return file;
  }

  try {
    // First pass keeps the source's own nature: PNG stays lossless (alpha survives),
    // everything else becomes a good-quality JPEG.
    const keepPng = file.type === "image/png";
    const first = await encodeScaled(
      bitmap,
      MAX_EDGE,
      keepPng ? "image/png" : "image/jpeg",
      keepPng ? undefined : 0.85,
    );
    if (first && first.size <= UPLOAD_CAP_BYTES && first.size < file.size) {
      return toFile(first, file.name);
    }
    // A re-encode can come out bigger (already-optimised files); never make it worse —
    // but only when the original itself fits under the cap.
    if (file.size <= UPLOAD_CAP_BYTES) return file;

    // Still over the cap (a big PNG, usually). Walk down until something fits: WebP
    // keeps alpha where the browser can encode it; the JPEG steps matte onto white.
    const ladder: { type: string; quality: number; edge: number }[] = [
      { type: "image/webp", quality: 0.85, edge: MAX_EDGE },
      { type: "image/webp", quality: 0.75, edge: 2048 },
      { type: "image/jpeg", quality: 0.8, edge: 2048 },
      { type: "image/jpeg", quality: 0.65, edge: 1600 },
      { type: "image/jpeg", quality: 0.55, edge: 1280 },
    ];
    let smallest = first && first.size < file.size ? first : null;
    for (const step of ladder) {
      const blob = await encodeScaled(bitmap, step.edge, step.type, step.quality);
      if (!blob) continue;
      if (blob.size <= UPLOAD_CAP_BYTES) return toFile(blob, file.name);
      if (!smallest || blob.size < smallest.size) smallest = blob;
    }
    // Nothing fit (pathological input). Hand back the best attempt — the caller's cap
    // check turns it into a legible refusal instead of a dead request.
    return smallest ? toFile(smallest, file.name) : file;
  } finally {
    bitmap.close();
  }
}
