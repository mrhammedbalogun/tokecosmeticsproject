"use server";

/**
 * The delivery-partner portal login (Plan-39), as a Server Function for the same two
 * freebies the staff login chose one for: Next's Origin/Host check on every action,
 * and a redirect whose destination renders AFTER the cookies were staged.
 *
 * ONE step, not three: there is no TOTP behind this door (plan-39 ruling). The
 * backend's compensations are the failure-counting throttles and the staff
 * kill-switch; this action's only jobs are to forward the credentials, store the
 * pair, and translate refusals into one honest sentence.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError, apiFetch } from "@/lib/api";
import { PARTNER_HOME_PATH } from "@/lib/partner-auth";
import { clearPartnerSession, storePartnerSession } from "@/lib/partner-session";

export interface PartnerLoginState {
  error?: string;
  /** Echoed back so a failed attempt does not make the partner retype their address. */
  email?: string;
}

/** Same header + same rationale as `admin-session.ts`'s private `bffHeaders`: an
 * anti-abuse gate, not authentication, omitted (not blank) when unset. Duplicated
 * rather than exported because that module is the ADMIN credential's helper set and
 * this file must never import from it. */
function bffHeaders(): Record<string, string> {
  const secret = process.env.ADMIN_BFF_SECRET;
  return secret ? { "X-Admin-BFF-Secret": secret } : {};
}

export async function partnerLoginAction(
  _prev: PartnerLoginState,
  formData: FormData,
): Promise<PartnerLoginState> {
  const rawEmail = formData.get("email");
  const email = typeof rawEmail === "string" ? rawEmail.trim() : "";
  const password = formData.get("password");

  if (!email || typeof password !== "string" || !password) {
    return { error: "Enter your email and password.", email };
  }

  const jar = await cookies();
  try {
    const out = await apiFetch<{ access: string; refresh: string }>("/partner/auth/login/", {
      method: "POST",
      body: { email, password },
      headers: bffHeaders(),
    });
    storePartnerSession(jar, out);
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401) {
        return { error: "That email and password don't match an active partner account.", email };
      }
      if (e.status === 429) {
        return { error: "Too many attempts — wait a few minutes and try again.", email };
      }
    }
    return { error: "Something went wrong signing you in — please try again.", email };
  }
  // Outside the try: redirect() throws NEXT_REDIRECT.
  redirect(PARTNER_HOME_PATH);
}

export async function partnerLogoutAction(): Promise<void> {
  const jar = await cookies();
  // Local sign-out only: the refresh token is not blacklisted server-side (mirrors
  // the storefront's posture for its own low-privilege sessions). Clearing the pair
  // is what the proxy's presence check keys on.
  clearPartnerSession(jar);
  redirect("/partner/login");
}
