import { redirect } from "next/navigation";

/** Banners are edited on the Home Content page now (rework 2026-08-06), where every
 * tile shows in its homepage position. This route survives only for old bookmarks. */
export default function BannersPage() {
  redirect("/home-content");
}
