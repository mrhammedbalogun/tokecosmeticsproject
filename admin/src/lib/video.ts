/** Video upload limits.
 *
 * The 128MB ceiling mirrors the API's `MAX_VIDEO_BYTES` and is a guardrail, not a target:
 * a 3-minute film at 720p/~2Mbps lands around 45-55MB. Videos bypass Vercel entirely
 * (see lib/upload.ts), so the ~4MB request cap in lib/image.ts does not apply to them.
 */
export const VIDEO_CAP_BYTES = 128_000_000;

/** Above this, a LOOPING video is worth warning about — it autoplays for every visitor,
 * many on mobile data. Click-to-play videos are opt-in and get no warning. */
export const LOOP_WARN_BYTES = 6_000_000;

export function fileSizeMb(file: { size: number }): string {
  return `${(file.size / 1_000_000).toFixed(1)} MB`;
}
