"use server";

/**
 * Accepting a staff invite. A PUBLIC entry point, deliberately: the person accepting has
 * no account yet (or a customer account whose credentials are irrelevant here), and the
 * proof they present is the token from their inbox.
 *
 * It lands them in exactly the same place a password login does — holding a preauth token,
 * owing a second factor. One bootstrap path, not two.
 *
 * THE TOKEN ARRIVES IN THE URL, which is only acceptable because of the standing rule
 * written down in `next.config.ts`: this origin runs ZERO third-party scripts, ever. A
 * token in a URL is readable by every script on the page; with none but our own and
 * Turnstile's, its exposure is the recipient's inbox and their own browser history, which
 * is the exposure the backend already accepts (`StaffInviteAcceptView`).
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError } from "@/lib/api";
import { acceptInvite } from "@/lib/admin-session";
import { acceptInviteErrorMessage } from "@/lib/auth-errors";
import { TOTP_PATH } from "@/lib/auth-guard";

export interface AcceptInviteState {
  error?: string;
}

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export async function acceptInviteAction(
  _prev: AcceptInviteState,
  formData: FormData,
): Promise<AcceptInviteState> {
  const token = field(formData, "token");
  const password = formData.get("password");
  const confirm = formData.get("password_confirm");

  if (!token) return { error: "That invite link is not valid. Ask for a new one." };
  if (typeof password !== "string" || !password) {
    return { error: "Choose a password." };
  }
  // Checked here rather than only in the browser: a Server Action is a public POST
  // endpoint, and a mismatched password on a SINGLE-USE invite would burn the capability
  // and strand the new hire.
  if (password !== confirm) return { error: "The two passwords do not match." };

  const turnstileToken = field(formData, "cf-turnstile-response") || undefined;

  try {
    await acceptInvite(await cookies(), { token, password }, { turnstileToken });
  } catch (e) {
    if (e instanceof ApiError) return { error: acceptInviteErrorMessage(e.status, e.data) };
    return { error: acceptInviteErrorMessage(500, null) };
  }

  // Straight into enrolment: a brand-new staff account has no authenticator yet, and the
  // account reaches nothing at all until it does.
  redirect(`${TOTP_PATH}?setup=1`);
}
