/**
 * Turn a Django/DRF error body into one string a shopper can act on.
 *
 * The rule that shapes this file: a sign-in form must never reveal whether an email has
 * an account. `TokenObtainPairView` is already careful — it returns the same
 * "No active account found with the given credentials" for a wrong password and for an
 * address that has never registered — and the UI must not undo that by guessing. So every
 * 401 gets one identical message, and "inactive account" is not distinguished either.
 *
 * (Checkout's `SignInStep` says "Incorrect password — please try again.", which asserts
 * the account exists. That is safe *there* only because it reaches its login phase via a
 * register attempt that already established existence. Do not copy it onto /login.)
 *
 * Upstream strings are only ever shown when they are field-validation messages, which are
 * written for end users. A 5xx body is not, and may carry internals, so it is replaced.
 */

/** DRF sends `{detail}` for a top-level problem and `{field: ["msg", ...]}` for validation. */
type ErrorBody = { detail?: unknown } & Record<string, unknown>;

const REJECTED = "Email or password is incorrect.";
const THROTTLED = "Too many sign-in attempts. Please wait a minute and try again.";
const UNEXPECTED = "Something went wrong signing you in — please try again.";

function fieldMessages(body: ErrorBody): string[] {
  return Object.entries(body)
    .filter(([key]) => key !== "detail")
    .flatMap(([, value]) =>
      Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [],
    );
}

export function loginErrorMessage(status: number, body: unknown): string {
  // Identical copy for every credential rejection — see the file comment.
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
