"use client";
import { useEffect } from "react";
import { pushRecentlyViewed, type RecentEntry } from "@/lib/recently-viewed";

export function RecentlyViewedTracker({ entry }: { entry: RecentEntry }) {
  useEffect(() => { pushRecentlyViewed(entry); }, [entry]);
  return null;
}
