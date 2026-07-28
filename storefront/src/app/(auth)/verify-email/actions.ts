"use server";

/**
 * Confirm an email address. Called only from an explicit button press — never during page
 * render. That distinction is the whole point of this file; see `page.tsx`.
 *
 * Deliberately anonymous (`apiFetch`, no token): the link is clicked from an email, often
 * in a browser with no session, and `VerifyEmailView` is `AllowAny` because the signed
 * token is the credential. Attaching whatever session happens to be in this browser would
 * imply the two must match, which they need not.
 */
import { apiFetch, ApiError } from "@/lib/api";

export interface VerifyState {
  verified?: boolean;
  error?: string;
  /** Past orders placed with this address that the confirmation linked to the account. */
  ordersClaimed?: number;
}

interface VerifyResponse {
  detail?: string;
  orders_claimed?: number;
}

export async function verifyEmailAction(
  _prevState: VerifyState,
  formData: FormData,
): Promise<VerifyState> {
  const token = formData.get("token");
  if (typeof token !== "string" || !token.trim()) {
    return { verified: false, error: "This confirmation link is missing its token." };
  }

  try {
    const out = await apiFetch<VerifyResponse>("/auth/verify-email/", {
      method: "POST", body: { token },
    });
    return { verified: true, ordersClaimed: out.orders_claimed ?? 0 };
  } catch (e) {
    // A 400 here is routine, not exceptional: tokens are single-use and expire after 7
    // days, so a re-clicked or old link lands here and must read as a normal outcome.
    if (e instanceof ApiError && e.status === 400) {
      const detail = typeof (e.data as VerifyResponse)?.detail === "string"
        ? (e.data as VerifyResponse).detail!
        : "This confirmation link is invalid or has expired.";
      return { verified: false, error: detail };
    }
    // Anything else is ours, not the user's — never surface an upstream 5xx body.
    return {
      verified: false,
      error: "We couldn't confirm your email just now. Please try again in a moment.",
    };
  }
}
