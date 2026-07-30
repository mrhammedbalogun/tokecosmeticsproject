/**
 * `/auth/admin-me/` — who the signed-in staff member is and what they may do.
 *
 * Used only to decide which nav items exist. It is NOT a gate: each page calls
 * `requireAdmin`, and every endpoint behind every nav item carries its own
 * `HasAdminScope`, re-read from the database on each request.
 */
import { cookies } from "next/headers";
import { apiFetch } from "@/lib/api";
import { ACCESS_COOKIE } from "@/lib/auth";

export interface AdminMe {
  email: string;
  name: string;
  is_superuser: boolean;
  groups: string[];
  scopes: string[];
}

/**
 * Read-only and failure-tolerant, because it is called from the shell LAYOUT.
 *
 * Layouts must never gate (Plan-15's lesson: they do not re-render on every client
 * navigation, so a check placed there is a check that sometimes does not run). This helper
 * therefore never redirects and never refreshes — it reads the access cookie, and on
 * anything at all going wrong it answers `null` and the shell renders with no nav. The
 * page rendering inside that shell has already called `requireAdmin`, which is what
 * actually decides whether anything renders at all.
 */
export async function getAdminMeOrNull(): Promise<AdminMe | null> {
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) return null;
  try {
    return await apiFetch<AdminMe>("/auth/admin-me/", { token });
  } catch {
    return null;
  }
}
