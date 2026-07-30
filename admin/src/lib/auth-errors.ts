/**
 * Turn a Django/DRF error body into one string a staff member can act on.
 *
 * Same rule as the storefront's version, applied harder: the staff gate must never
 * distinguish "wrong password" from "that address is not staff" from "no such account".
 * `AdminPasswordSerializer` is already careful to answer identically for all three, and
 * this file must not undo that by guessing from a status code.
 *
 * A 5xx body may carry internals and is never shown.
 */
type ErrorBody = { detail?: unknown } & Record<string, unknown>;

const REJECTED = "Email or password is incorrect.";
const THROTTLED = "Too many attempts. Wait a minute and try again.";
const UNEXPECTED = "Something went wrong — please try again.";

/**
 * A 403 does not mean "bad credentials" here: the backend answers 403 with a
 * "Human verification failed…" detail when Turnstile refuses. Telling that person their
 * password is wrong sends them to reset a password that was never the problem.
 */
function turnstileMessage(status: number, body: unknown): string | null {
  if (status !== 403) return null;
  const detail = body && typeof body === "object" ? (body as ErrorBody).detail : null;
  return typeof detail === "string" && /verification/i.test(detail) ? detail : null;
}

function fieldMessages(body: ErrorBody): string[] {
  return Object.entries(body)
    .filter(([key]) => key !== "detail")
    .flatMap(([, value]) =>
      Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [],
    );
}

export function adminLoginErrorMessage(status: number, body: unknown): string {
  const turnstile = turnstileMessage(status, body);
  if (turnstile) return turnstile;
  if (status === 401 || status === 403) return REJECTED;
  if (status === 429) return THROTTLED;

  const shape: ErrorBody = body && typeof body === "object" ? (body as ErrorBody) : {};
  if (status === 400) {
    const messages = fieldMessages(shape);
    if (messages.length) return messages.join(" ");
    if (typeof shape.detail === "string") return shape.detail;
  }
  return UNEXPECTED;
}

/**
 * TOTP and recovery-code errors. The backend answers every rejection — wrong code,
 * replayed code, unknown recovery code — with one identical message on purpose, so
 * echoing its `detail` verbatim is both the most useful and the most discreet thing to do.
 *
 * 429 here is the per-user hourly hard deny, which is a genuinely different situation from
 * an ordinary rate limit and says so.
 */
export function totpErrorMessage(status: number, body: unknown): string {
  if (status === 429) {
    return "Too many incorrect codes. Verification is locked for up to an hour — contact the site operator.";
  }
  if (status === 409) {
    return "Two-factor authentication is already set up on this account. Enter a code from your authenticator app, or use a recovery code.";
  }
  const shape: ErrorBody = body && typeof body === "object" ? (body as ErrorBody) : {};
  if (typeof shape.detail === "string") return shape.detail;
  const messages = fieldMessages(shape);
  if (messages.length) return messages.join(" ");
  return UNEXPECTED;
}

/**
 * Invite-acceptance errors. Django's password validators ARE the instruction
 * ("This password is too short.") and are echoed verbatim; the invite-token messages are
 * written for end users too, and already say the same thing for unknown, revoked and
 * already-used tokens.
 */
export function acceptInviteErrorMessage(status: number, body: unknown): string {
  const turnstile = turnstileMessage(status, body);
  if (turnstile) return turnstile;
  if (status === 429) return THROTTLED;

  const shape: ErrorBody = body && typeof body === "object" ? (body as ErrorBody) : {};
  if (status === 400) {
    const messages = fieldMessages(shape);
    if (messages.length) return messages.join(" ");
    if (typeof shape.detail === "string") return shape.detail;
  }
  return UNEXPECTED;
}
