"use server";

/**
 * Account creation as a Server Function, mirroring `/login`.
 *
 * Same reasons as login, and one extra: routing this through the JSON auth BFF instead
 * would extend the surface of a known gap — that route has no `Origin` check, whereas Next
 * compares `Origin` to `Host` on every Server Action
 * (`server-actions.md:82`). Registration is the more attractive target of the two, because
 * a cross-site POST that creates *and* logs into an attacker-chosen account is session
 * fixation with the guest cart folded in.
 *
 * The two-call register-then-login sequence lives in `lib/auth-session.ts`, shared with
 * that BFF route so the pair cannot drift.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { parsePhoneNumberFromString } from "libphonenumber-js";
import { ApiError } from "@/lib/api";
import { registerSession } from "@/lib/auth-session";
import { registerErrorMessage } from "@/lib/auth-errors";
import { DEFAULT_NEXT, safeNext } from "@/lib/next-param";

export interface RegisterState {
  error?: string;
  /** The address is already registered — the form offers sign-in instead. */
  emailTaken?: boolean;
  email?: string;
  firstName?: string;
  lastName?: string;
  /** E.164 echoes for the PhoneField defaults. */
  phone?: string;
  whatsapp?: string;
  /** Always the SANITISED value. */
  next?: string;
}

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

/** "" for empty, E.164 for a valid number, null for garbage. The PhoneField already
 * submits E.164, so this only rejects hand-crafted POSTs — but the backend re-checks
 * regardless; this just gives a friendlier error without a round trip. */
function e164Field(formData: FormData, name: string): string | null {
  const raw = field(formData, name);
  if (!raw) return "";
  const parsed = parsePhoneNumberFromString(raw);
  return parsed?.isValid() ? parsed.number : null;
}

export async function registerAction(
  _prevState: RegisterState,
  formData: FormData,
): Promise<RegisterState> {
  const email = field(formData, "email");
  const firstName = field(formData, "first_name");
  const lastName = field(formData, "last_name");
  const password = formData.get("password");
  // Re-validated here even though the page validated it: a Server Action is a public POST
  // endpoint, so the hidden input is not a trust boundary. The sanitised value also goes
  // back into the re-rendered form, so a hostile value cannot survive into the next submit.
  const next = safeNext(field(formData, "next"), DEFAULT_NEXT);
  const phone = e164Field(formData, "phone");
  const whatsapp = e164Field(formData, "whatsapp");
  const echo = { email, firstName, lastName, phone: phone ?? "", whatsapp: whatsapp ?? "", next };

  if (!email || !firstName || typeof password !== "string" || !password) {
    return { ...echo, error: "Enter your name, email and a password." };
  }
  if (phone === null || !phone || whatsapp === null) {
    return {
      ...echo,
      error: "Enter your phone number with its country code, e.g. +2348023900964.",
    };
  }

  // Injected by the Turnstile widget as a hidden input; absent when the widget is
  // off or blocked. One token covers the whole signup — register returns the pair.
  const turnstileToken = field(formData, "cf-turnstile-response") || undefined;

  try {
    await registerSession(await cookies(), {
      email,
      password,
      first_name: firstName,
      ...(lastName ? { last_name: lastName } : {}),
      phone,
      ...(whatsapp ? { whatsapp } : {}),
      // An unticked checkbox is absent from FormData entirely. Send an explicit false
      // rather than omitting the key, so the stored value always reflects a real choice.
      marketing_consent: formData.get("marketing_consent") !== null,
    }, { turnstileToken });
  } catch (e) {
    const { message, emailTaken } = e instanceof ApiError
      ? registerErrorMessage(e.status, e.data)
      : registerErrorMessage(500, null);
    return { ...echo, error: message, emailTaken };
  }

  // Outside the try — redirect() throws NEXT_REDIRECT (`redirect.md:52`).
  redirect(next);
}
