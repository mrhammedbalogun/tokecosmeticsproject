"use server";

/**
 * Set a new password from an emailed reset link. Anonymous like verify-email: the
 * signed uid+token pair IS the credential, and the link is often opened in a
 * browser with no session.
 *
 * The `confirm` field is a UI-only typo check and never travels upstream — the
 * backend contract is exactly {uid, token, password}. Not Turnstile-gated: the
 * token already proves a human read the mailbox, and the endpoint is throttled.
 */
import { apiFetch, ApiError } from "@/lib/api";
import { resetConfirmErrorMessage } from "@/lib/auth-errors";

export interface ResetState {
  done?: boolean;
  error?: string;
}

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

export async function confirmResetAction(
  _prevState: ResetState,
  formData: FormData,
): Promise<ResetState> {
  // Hidden inputs are client-supplied; a Server Action is a public POST endpoint.
  // Absent uid/token means a mangled link, not a user mistake they can correct here.
  const uid = field(formData, "uid").trim();
  const token = field(formData, "token").trim();
  if (!uid || !token) {
    return { error: "This reset link is incomplete — please use the link from your email again." };
  }

  const password = field(formData, "password");
  const confirm = field(formData, "confirm");
  if (!password) return { error: "Enter a new password." };
  if (password !== confirm) return { error: "The two passwords don't match." };

  try {
    await apiFetch("/auth/password/reset/confirm/", {
      method: "POST", body: { uid, token, password },
    });
  } catch (e) {
    if (e instanceof ApiError) {
      return { error: resetConfirmErrorMessage(e.status, e.data) };
    }
    return { error: resetConfirmErrorMessage(500, null) };
  }

  return { done: true };
}
