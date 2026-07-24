/** Backend media URLs come back relative ("/media/..."). Absolutise against the
 * API origin so next/image and Open Graph tags work. NEXT_PUBLIC_API_URL is used
 * (not API_URL) because the value is embedded in HTML sent to the browser. */
export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return `${base}${path}`;
}
