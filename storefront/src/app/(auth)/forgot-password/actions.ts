"use server";

/**
 * Request a password-reset email. Anonymous on purpose (no session attached) and it
 * NEVER reveals whether the address has an account — the backend always 200s, and
 * this action reports "sent" for every accepted request. The only visible failures
 * are the Turnstile gate, the throttle, and our own errors.
 */
import { apiFetch, ApiError } from "@/lib/api";
import { resetRequestErrorMessage } from "@/lib/auth-errors";

export interface ForgotState {
  sent?: boolean;
  error?: string;
  /** Echoed back so a failed attempt does not make the user retype their address. */
  email?: string;
}

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export async function requestResetAction(
  _prevState: ForgotState,
  formData: FormData,
): Promise<ForgotState> {
  const email = field(formData, "email");
  if (!email) return { error: "Enter your email address." };

  // Injected by the Turnstile widget; absent when the widget is off or blocked.
  const turnstileToken = field(formData, "cf-turnstile-response") || undefined;

  try {
    await apiFetch("/auth/password/reset/", {
      method: "POST",
      body: {
        email,
        ...(turnstileToken ? { turnstile_token: turnstileToken } : {}),
      },
    });
  } catch (e) {
    if (e instanceof ApiError) {
      return { error: resetRequestErrorMessage(e.status, e.data), email };
    }
    return { error: resetRequestErrorMessage(500, null), email };
  }

  return { sent: true, email };
}
