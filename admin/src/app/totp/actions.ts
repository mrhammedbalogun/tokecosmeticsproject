"use server";

/**
 * Steps two and three of the staff ceremony: the second factor.
 *
 * FOUR SERVER FUNCTIONS FOR FOUR BACKEND ENDPOINTS, and no fifth. The preauth token in
 * the `admin_preauth` cookie opens exactly those four — TOTP enrol, second-factor
 * confirm, recovery, and the email-code send (`AdminPreauthJWTAuthentication` + an
 * enumerated, guard-tested allowlist on the Django side) — so anything else this module
 * grew would 401 anyway. A good property to state out loud, because it means a
 * mistake here is a bug and not a hole.
 *
 * A STALE PREAUTH TOKEN IS HANDLED IN ONE PLACE, `withPreauth` below: the backend 401s, the
 * cookie is cleared, and the staff member lands on `/login`. That is the fifth row of the
 * gate matrix ("expired preauth"), and it is why that row needs no state of its own —
 * clearing collapses it into "no cookies".
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError } from "@/lib/api";
import {
  clearSession,
  confirmSecondFactor,
  enrolTotp,
  recoverTotp,
  requestEmailOtp,
  type EnrolResponse,
} from "@/lib/admin-session";
import { totpErrorMessage } from "@/lib/auth-errors";
import { PREAUTH_COOKIE } from "@/lib/auth";
import { LOGIN_PATH, TOTP_PATH } from "@/lib/auth-guard";
import { DEFAULT_NEXT, safeNext } from "@/lib/next-param";

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

/**
 * Run `fn` with the preauth token, or bounce to `/login` with the cookies cleared.
 *
 * The bounce is a `redirect()`, so it throws — which is correct here and is why every
 * caller keeps its own try/catch narrow enough not to swallow it.
 */
async function withPreauth<T>(fn: (token: string) => Promise<T>): Promise<T> {
  const jar = await cookies();
  const token = jar.get(PREAUTH_COOKIE)?.value;
  if (!token) {
    clearSession(jar);
    redirect(LOGIN_PATH);
  }
  try {
    return await fn(token);
  } catch (e) {
    // 401 from any of the three means the token is dead: expired, or invalidated after
    // five wrong codes (`totp.record_preauth_failure`). Either way there is nothing left
    // to do with it, and leaving it in the jar would strand the browser on a page whose
    // every button now fails.
    if (e instanceof ApiError && e.status === 401) {
      clearSession(jar);
      redirect(`${LOGIN_PATH}`);
    }
    throw e;
  }
}

// ── enrol ────────────────────────────────────────────────────────────────────────────

export interface EnrolState {
  error?: string;
  /** Present once the secret has been issued. NEVER logged, never stored — the response
   *  that carries it is the only copy that ever leaves Django in plaintext. */
  enrolment?: EnrolResponse;
}

/** Nullary on purpose: `useActionState` supplies `(prevState, formData)` and this step
 *  needs neither — the only input is the preauth cookie. */
export async function enrolAction(): Promise<EnrolState> {
  try {
    return { enrolment: await withPreauth((token) => enrolTotp(token)) };
  } catch (e) {
    if (e instanceof ApiError) return { error: totpErrorMessage(e.status, e.data) };
    throw e;
  }
}

// ── confirm ──────────────────────────────────────────────────────────────────────────

export interface ConfirmState {
  error?: string;
  /** Issued ONCE, on the response that confirms a new enrolment. Shown to the staff member
   *  and never persisted anywhere by this app. */
  recoveryCodes?: string[];
  /** Where to go once the codes have been acknowledged. */
  next?: string;
}

export async function confirmAction(
  _prev: ConfirmState,
  formData: FormData,
): Promise<ConfirmState> {
  const code = field(formData, "code");
  const next = safeNext(field(formData, "next"), DEFAULT_NEXT);
  // Which method the form is verifying — a UI fact like `next`, not a privilege: the
  // backend re-derives what the account is allowed to verify with and refuses the
  // rest, so a hand-edited hidden input changes an error message and nothing else.
  const method = field(formData, "method") === "email" ? "email" : "totp";
  const trustDevice = field(formData, "trust_device") === "on";
  if (!code) {
    return {
      error:
        method === "email"
          ? "Enter the six-digit code from your email."
          : "Enter the six-digit code from your authenticator app.",
      next,
    };
  }

  let codes: string[] | undefined;
  try {
    const jar = await cookies();
    const out = await withPreauth((token) =>
      confirmSecondFactor(jar, token, { method, code, trustDevice }),
    );
    codes = out.recovery_codes;
  } catch (e) {
    if (e instanceof ApiError) return { error: totpErrorMessage(e.status, e.data), next };
    throw e;
  }

  // A first confirmation returns recovery codes, which exist in exactly one place: this
  // response. They are handed to the client to be shown once, and the staff member
  // continues manually — redirecting past them would throw away the only copy.
  if (codes?.length) return { recoveryCodes: codes, next };

  redirect(next);
}

// ── email code ───────────────────────────────────────────────────────────────────────

export interface EmailOtpState {
  error?: string;
  /** Set once a send has been asked for. `retryAfter` is how long the resend button
   *  should stay quiet — the backend's answer, not a client-side guess. */
  sent?: boolean;
  retryAfter?: number;
}

/**
 * Ask the backend to mail a code to the signing-in account's own inbox. Nullary like
 * `enrolAction` and for the same reason: the only input is the preauth cookie — the
 * backend derives the address from it, so there is nothing here a form could aim.
 * Safe to re-run: inside the cooldown it is a 200 that sends nothing.
 */
export async function emailOtpAction(): Promise<EmailOtpState> {
  try {
    const out = await withPreauth((token) => requestEmailOtp(token));
    return { sent: true, retryAfter: out.retry_after };
  } catch (e) {
    if (e instanceof ApiError) return { error: totpErrorMessage(e.status, e.data) };
    throw e;
  }
}

// ── recovery ─────────────────────────────────────────────────────────────────────────

export interface RecoveryState {
  error?: string;
}

/**
 * Burn a recovery code. Mints nothing: the backend voids the enrolment and the remaining
 * codes and hands the person back to enrolment, still holding the same preauth token.
 */
export async function recoveryAction(
  _prev: RecoveryState,
  formData: FormData,
): Promise<RecoveryState> {
  const code = field(formData, "code");
  const next = safeNext(field(formData, "next"), DEFAULT_NEXT);
  if (!code) return { error: "Enter one of your recovery codes." };

  try {
    await withPreauth((token) => recoverTotp(token, code));
  } catch (e) {
    if (e instanceof ApiError) return { error: totpErrorMessage(e.status, e.data) };
    throw e;
  }

  redirect(`${TOTP_PATH}?${new URLSearchParams({ next, setup: "1" }).toString()}`);
}
