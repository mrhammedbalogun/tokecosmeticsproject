"use client";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCheckout } from "@/components/checkout/CheckoutContext";
import { readBuyNowIntent, clearBuyNowIntent } from "@/lib/buynow-intent";

/** Django field errors come back as `{ field: ["message", ...] }`; a top-level
 * problem (e.g. login's "No active account found...") comes back as `{ detail }`. */
interface ApiErrorBody {
  detail?: string;
  email?: string[];
  password?: string[];
  first_name?: string[];
}

type Phase = "checking" | "register" | "login";

/** Step 1 of checkout: guarantee a logged-in user before the shopper can reach
 * Review (the backend forces auth on order placement — see Plan-14 design D3).
 *
 * - Already signed in (GET-equivalent `me` check) → auto-completes silently.
 * - Guest → email + first name + password → silent account creation (register),
 *   auto-logged-in by the auth BFF.
 * - If that email already has an account, the backend reports it via a 400 with
 *   an `email` field error ("Account already exists") — flip to a password-only
 *   login form instead of erroring out.
 * - Either path ends with the Buy-Now guest-resume routine: if the shopper
 *   arrived here via a guest "Buy Now" click (intent stashed in sessionStorage
 *   by BuyButtons.tsx), add that item to their now-authenticated cart.
 */
export function SignInStep() {
  const { complete } = useCheckout();
  const queryClient = useQueryClient();

  const [phase, setPhase] = useState<Phase>("checking");
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<ApiErrorBody>({});

  // One-shot mount check: is there already a signed-in session (cookie)? Guarded by
  // a ref so a dev-mode double-effect (or a StrictMode remount) never double-fires
  // the auto-complete. The setState calls below happen after an awaited fetch, not
  // synchronously in the effect body, so they don't trip react-hooks/set-state-in-effect
  // the way a bare mount-flag set (see CountrySuggestionBanner.tsx) would.
  const checkedRef = useRef(false);
  useEffect(() => {
    if (checkedRef.current) return;
    checkedRef.current = true;
    (async () => {
      try {
        const res = await fetch("/api/auth/me", { method: "POST" });
        if (res.ok) {
          const me = await res.json().catch(() => null);
          if (me?.email) {
            await runPostAuth(me.email);
            return;
          }
        }
      } catch {
        // Network hiccup on the silent check — fall through to the guest form;
        // the shopper can still sign in/register explicitly.
      }
      setPhase("register");
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot mount check only
  }, []);

  /** Buy-Now guest resume: best-effort — a failure here must never block checkout,
   * since the item may already be in the cart (or the shopper can re-add it). */
  async function runPostAuth(userEmail: string) {
    const intent = readBuyNowIntent();
    if (intent) {
      try {
        await fetch("/api/checkout/buy-now", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(intent),
        });
      } catch {
        // swallow — see doc comment above
      } finally {
        clearBuyNowIntent();
        queryClient.invalidateQueries({ queryKey: ["cart"] });
      }
    }
    complete(1, { userEmail });
  }

  function looksLikeDuplicateEmail(body: ApiErrorBody): boolean {
    return Array.isArray(body.email) && body.email.some((m) => /already exists/i.test(m));
  }

  async function submitRegister(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    setFieldErrors({});
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password, first_name: firstName }),
      });
      if (res.ok) {
        await runPostAuth(email);
        return;
      }
      const body: ApiErrorBody = await res.json().catch(() => ({}));
      if (res.status === 400 && looksLikeDuplicateEmail(body)) {
        setPhase("login");
        setPassword("");
        return;
      }
      setFieldErrors(body);
      if (body.detail) setFormError(body.detail);
      else if (!body.email && !body.password && !body.first_name) {
        setFormError("Something went wrong creating your account — please try again.");
      }
    } catch {
      setFormError("Something went wrong creating your account — please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function submitLogin(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    setFieldErrors({});
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (res.ok) {
        await runPostAuth(email);
        return;
      }
      const body: ApiErrorBody = await res.json().catch(() => ({}));
      setFormError(body.detail ?? "Incorrect password — please try again.");
    } catch {
      setFormError("Something went wrong signing you in — please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (phase === "checking") {
    return <p className="text-sm text-muted">Checking your account…</p>;
  }

  if (phase === "login") {
    return (
      <form onSubmit={submitLogin} className="space-y-4" noValidate>
        <p className="text-sm text-muted">
          This email already has an account — enter your password to continue.
        </p>
        <div aria-live="polite">
          {formError && (
            <p role="alert" className="text-sm text-red-700">
              {formError}
            </p>
          )}
        </div>
        <div>
          <label htmlFor="signin-email" className="mb-1 block text-sm font-medium">
            Email
          </label>
          <input
            id="signin-email"
            type="email"
            value={email}
            readOnly
            className="w-full rounded-[var(--radius-card)] border border-line bg-beige/60 px-3 py-2 text-sm text-muted"
          />
        </div>
        <div>
          <label htmlFor="signin-password" className="mb-1 block text-sm font-medium">
            Password
          </label>
          <input
            id="signin-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={submitting || !password}
          className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
        <button
          type="button"
          onClick={() => {
            setPhase("register");
            setPassword("");
            setFormError(null);
          }}
          className="block text-sm text-muted underline hover:text-foreground"
        >
          Use a different email
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={submitRegister} className="space-y-4" noValidate>
      <div aria-live="polite">
        {formError && (
          <p role="alert" className="text-sm text-red-700">
            {formError}
          </p>
        )}
      </div>
      <div>
        <label htmlFor="signin-email" className="mb-1 block text-sm font-medium">
          Email
        </label>
        <input
          id="signin-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
          className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
        />
        {fieldErrors.email && (
          <p role="alert" className="mt-1 text-sm text-red-700">
            {fieldErrors.email.join(" ")}
          </p>
        )}
      </div>
      <div>
        <label htmlFor="signin-first-name" className="mb-1 block text-sm font-medium">
          First name
        </label>
        <input
          id="signin-first-name"
          type="text"
          value={firstName}
          onChange={(e) => setFirstName(e.target.value)}
          required
          autoComplete="given-name"
          className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
        />
        {fieldErrors.first_name && (
          <p role="alert" className="mt-1 text-sm text-red-700">
            {fieldErrors.first_name.join(" ")}
          </p>
        )}
      </div>
      <div>
        <label htmlFor="signin-password" className="mb-1 block text-sm font-medium">
          Password
        </label>
        <input
          id="signin-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="new-password"
          className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
        />
        {fieldErrors.password && (
          <p role="alert" className="mt-1 text-sm text-red-700">
            {fieldErrors.password.join(" ")}
          </p>
        )}
      </div>
      <button
        type="submit"
        disabled={submitting || !email || !firstName || !password}
        className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
      >
        {submitting ? "Creating account…" : "Continue"}
      </button>
    </form>
  );
}
