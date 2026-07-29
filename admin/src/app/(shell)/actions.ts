"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { adminLogout } from "@/lib/admin-session";
import { LOGIN_PATH } from "@/lib/auth-guard";

/**
 * Sign out. Clears all three cookies and blacklists the refresh token server-side.
 *
 * THE REVOCATION IS REAL, not a gesture: `rest_framework_simplejwt.token_blacklist` is in
 * INSTALLED_APPS, so `/auth/logout/` genuinely kills the refresh token and no further
 * renewal can succeed. The 10-minute access token is NOT revocable and stays valid until
 * it expires — which is the honest reason that lifetime is ten minutes and not an hour.
 * `docs/runbooks/admin-gate.md` says the same thing, so nobody has to read this file to
 * know what sign-out does and does not guarantee.
 */
export async function signOutAction(): Promise<void> {
  await adminLogout(await cookies());
  redirect(LOGIN_PATH);
}
