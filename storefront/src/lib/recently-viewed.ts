/** localStorage ring buffer for the PDP "recently viewed" strip (master spec —
 * client-side only, nothing tracked server-side). Snapshots are display-only;
 * prices may go stale, which is acceptable for this strip. */
export const RECENT_KEY = "toke-recently-viewed";
const MAX = 8;

export interface RecentEntry {
  slug: string; name: string; image: string | null;
  from_price: string | null; currency: string;
}

export function listRecentlyViewed(): RecentEntry[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(raw) ? (raw as RecentEntry[]) : [];
  } catch {
    return [];
  }
}

export function pushRecentlyViewed(entry: RecentEntry): void {
  if (typeof localStorage === "undefined") return;
  const next = [entry, ...listRecentlyViewed().filter((e) => e.slug !== entry.slug)].slice(0, MAX);
  localStorage.setItem(RECENT_KEY, JSON.stringify(next));
}
