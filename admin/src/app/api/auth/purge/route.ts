/**
 * Throw the session away and return to `/login`. Twelve lines, and it exists for one
 * reason that is not obvious until it bites.
 *
 * WHY A PAGE CANNOT DO THIS ITSELF. A Server Component may READ cookies but never write
 * them, so `jar.delete()` during a page render throws — the anomaly row of the gate matrix
 * (`admin_preauth` alongside a session pair) answered **500** rather than clearing and
 * redirecting, and `/login` carrying that state was an infinite redirect because nothing
 * in the cycle could remove the cookies. Found by walking the matrix over real HTTP
 * against a production build; the pure-function tests could not show it, because the
 * function's answer was right all along.
 *
 * A GET because it is reached by redirecting a navigating browser. It is safe to expose:
 * the only thing it can do to an attacker who calls it is sign somebody out, which is the
 * failure direction that costs nothing.
 */
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { clearSession } from "@/lib/admin-session";
import { LOGIN_PATH } from "@/lib/auth-guard";

export async function GET(req: Request) {
  clearSession(await cookies());
  return NextResponse.redirect(new URL(LOGIN_PATH, new URL(req.url).origin), 303);
}
