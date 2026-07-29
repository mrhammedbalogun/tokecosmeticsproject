"use server";

/**
 * Steps two and three of the staff ceremony: the TOTP factor.
 *
 * THREE SERVER FUNCTIONS FOR THREE BACKEND ENDPOINTS, and no fourth. The preauth token in
 * the `admin_preauth` cookie opens exactly those three (`AdminPreauthJWTAuthentication` +
 * an enumerated, guard-tested allowlist on the Django side), so anything else this module
 * grew would 401 anyway — which is a good property to state out loud, because it means a
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
  confirmTotp,
  enrolTotp,
  recoverTotp,
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
  if (!code) return { error: "Enter the six-digit code from your authenticator app.", next };

  let codes: string[] | undefined;
  try {
    const jar = await cookies();
    const out = await withPreauth((token) => confirmTotp(jar, token, code));
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
