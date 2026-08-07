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
 * PNG stays PNG (alpha survives), everything else becomes JPEG. GIF and SVG pass
 * through untouched — re-encoding would destroy animation / scalability. A file the
 * browser cannot decode (e.g. HEIC outside Safari) also passes through untouched and
 * the server gets to reject it legibly.
 */

/** Longest edge after downscaling; comfortably above any homepage render size. */
const MAX_EDGE = 2560;

/** Files at or under this size skip the round-trip — they already upload fine. */
const SKIP_UNDER_BYTES = 1_500_000;

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
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(bitmap, 0, 0, width, height);

    const keepPng = file.type === "image/png";
    const type = keepPng ? "image/png" : "image/jpeg";
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, type, keepPng ? undefined : 0.85),
    );
    // A re-encode can come out bigger (already-optimised files); never make it worse.
    if (!blob || blob.size >= file.size) return file;

    const name = keepPng ? file.name : file.name.replace(/\.\w+$/, "") + ".jpg";
    return new File([blob], name, { type });
  } finally {
    bitmap.close();
  }
}
