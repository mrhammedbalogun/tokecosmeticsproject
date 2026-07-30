"use server";

/**
 * Step one of the staff ceremony, as a Server Function rather than a client fetch.
 *
 * WHY A SERVER FUNCTION. Two things come free that a JSON BFF route would have to build:
 * Next compares `Origin` against `Host` on every Server Action (CSRF protection the
 * generic proxy gets from `SameSite=Strict` instead), and `redirect()` inside an action
 * serves a 303 and streams the destination's RSC payload in the SAME response — so the
 * page the browser lands on is rendered *after* the preauth cookie was staged. A client
 * fetch has no correct sequence for that.
 *
 * WHAT IT DOES NOT DO: mint a session. `/auth/admin-token/` returns a ten-minute preauth
 * token whether or not the caller has TOTP enrolled, and the only thing this action can do
 * with it is store it and send the staff member to the second factor.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError } from "@/lib/api";
import { adminLogin } from "@/lib/admin-session";
import { adminLoginErrorMessage } from "@/lib/auth-errors";
import { TOTP_PATH } from "@/lib/auth-guard";
import { DEFAULT_NEXT, safeNext } from "@/lib/next-param";

export interface LoginState {
  error?: string;
  /** Echoed back so a failed attempt does not make the staff member retype their address. */
  email?: string;
  /** Always the SANITISED value. */
  next?: string;
}

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export async function loginAction(
  _prevState: LoginState,
  formData: FormData,
): Promise<LoginState> {
  const email = field(formData, "email");
  const password = formData.get("password");
  // `next` arrives from a hidden input, so it is client-supplied: a Server Action is a
  // public POST endpoint. Re-validated here even though the page already validated it, and
  // the sanitised value is what goes back into the re-rendered form — sanitising only the
  // redirect would leave a hostile value in the field for the next submit.
  const next = safeNext(field(formData, "next"), DEFAULT_NEXT);

  if (!email || typeof password !== "string" || !password) {
    return { error: "Enter your email and password.", email, next };
  }

  // Injected by the Turnstile widget as a hidden input; absent when the widget is off or
  // blocked. Forwarded as-is — Django owns verification, because the API is reachable
  // directly and a BFF-side check would be decorative.
  const turnstileToken = field(formData, "cf-turnstile-response") || undefined;

  let enrolled = false;
  try {
    const out = await adminLogin(await cookies(), { email, password }, { turnstileToken });
    enrolled = Boolean(out.totp_enrolled);
  } catch (e) {
    if (e instanceof ApiError) return { error: adminLoginErrorMessage(e.status, e.data), email, next };
    return { error: adminLoginErrorMessage(500, null), email, next };
  }

  // `setup` is a HINT about which screen to draw, carried in the URL rather than in a
  // fourth cookie. It is not a branch in the security logic — the backend hands out the
  // same kind of token either way, and the TOTP page's own calls are what actually
  // discover the enrolment state (enrol 409s on a confirmed one; confirm refuses when
  // there is nothing enrolled).
  const query = new URLSearchParams({ next });
  if (!enrolled) query.set("setup", "1");
  // Outside the try: redirect() works by throwing NEXT_REDIRECT, and a catch above would
  // swallow it.
  redirect(`${TOTP_PATH}?${query.toString()}`);
}
