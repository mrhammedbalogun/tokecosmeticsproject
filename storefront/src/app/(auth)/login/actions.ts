"use server";

/**
 * Sign-in as a Server Function rather than a client fetch to the auth BFF.
 *
 * WHY, and it is about navigation more than progressive enhancement. `redirect()` inside a
 * Server Action serves a 303 and streams the destination's RSC payload in the SAME
 * response (`next/dist/docs/01-app/03-api-reference/04-functions/redirect.md:11`, and
 * `02-guides/server-actions.md:48`), so the page the user lands on is rendered *after* the
 * session cookies were staged. The client-fetch alternative has no correct sequence:
 * `router.refresh()` returns void with no completion signal, so a `push` cannot be ordered
 * after it, and the destination can render from a payload fetched before the cookies
 * existed.
 *
 * Two things come free: Next compares `Origin` against `Host` on every Server Action
 * (`server-actions.md:82`), which is CSRF protection the JSON BFF route does not have; and
 * the form submits without JavaScript.
 *
 * The session mechanics live in `lib/auth-session.ts`, shared with that BFF route — NOT
 * reached by fetching it, because `Set-Cookie` on a fetch response never propagates to the
 * outer response, so the user would authenticate and remain logged out.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError } from "@/lib/api";
import { establishSession } from "@/lib/auth-session";
import { loginErrorMessage } from "@/lib/auth-errors";
import { DEFAULT_NEXT, safeNext } from "@/lib/next-param";

export interface LoginState {
  error?: string;
  /** Echoed back so a failed attempt does not make the user retype their address. */
  email?: string;
  /** Always the SANITISED value — see below. */
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
  // public POST endpoint ("Treat every action as an untrusted entry point" —
  // server-actions.md:78). It is re-validated here even though the page already validated
  // it, and the sanitised value is what goes back into the re-rendered form: sanitising
  // only the redirect would leave a hostile value in the field for the next submit.
  const next = safeNext(field(formData, "next"), DEFAULT_NEXT);

  if (!email || typeof password !== "string" || !password) {
    return { error: "Enter your email and password.", email, next };
  }

  // Injected by the Turnstile widget as a hidden input; absent when the widget is
  // off or blocked. Forwarded as-is — Django owns verification and rejects with a
  // 403 that loginErrorMessage turns into user-facing copy.
  const turnstileToken = field(formData, "cf-turnstile-response") || undefined;

  try {
    await establishSession(await cookies(), { email, password }, { turnstileToken });
  } catch (e) {
    if (e instanceof ApiError) {
      return { error: loginErrorMessage(e.status, e.data), email, next };
    }
    return { error: loginErrorMessage(500, null), email, next };
  }

  // Outside the try: redirect() works by throwing NEXT_REDIRECT, and a catch above would
  // swallow it (redirect.md:52 — "call outside the try block").
  redirect(next);
}
