"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useCheckout } from "@/components/checkout/CheckoutContext";
import { useCart } from "@/hooks/useCart";
import { readBuyNowIntent, clearBuyNowIntent } from "@/lib/buynow-intent";
import { TurnstileWidget, turnstileToken } from "@/components/auth/TurnstileWidget";
import { PhoneField } from "@/components/ui/PhoneField";

/** Django field errors come back as `{ field: ["message", ...] }`; a top-level
 * problem (e.g. login's "No active account found...") comes back as `{ detail }`. */
interface ApiErrorBody {
  detail?: string;
  email?: string[];
  password?: string[];
  first_name?: string[];
  phone?: string[];
  whatsapp?: string[];
}

type Phase = "checking" | "register" | "login";

/** Step 1 of checkout: guarantee a logged-in user before the shopper can reach
 * Review (the backend forces auth on order placement — see Plan-14 design D3).
 *
 * - Already signed in (GET-equivalent `me` check) → auto-completes silently.
 * - Guest → the login form, matching the step's "Sign in" title: email + password,
 *   with "Forgot password?" (→ /forgot-password) and a toggle to the register form.
 * - Register form: email + first name + password → account creation, auto-logged-in
 *   by the auth BFF, with a toggle back to login.
 * - If a register attempt hits an email that already has an account, the backend
 *   reports it via a 400 with an `email` field error ("Account already exists") —
 *   flip to the login form with a notice instead of erroring out.
 * - The guest cart is merged into the new/matched account by the auth BFF itself
 *   (api/auth/[action]), not here — it belongs to authenticating, not to checkout.
 * - Either path then runs the Buy-Now guest-resume: if the shopper arrived via a
 *   guest "Buy Now" click (intent stashed in sessionStorage by BuyButtons.tsx),
 *   add that item to the now-authenticated cart. That one stays client-side
 *   because sessionStorage is invisible to the server.
 */
export function SignInStep() {
  const { complete } = useCheckout();
  const { cart } = useCart();
  const queryClient = useQueryClient();

  const [phase, setPhase] = useState<Phase>("checking");
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  // E.164 from the PhoneField ("" while empty/invalid), same as AddressStep.
  const [phone, setPhone] = useState("");
  const [whatsapp, setWhatsapp] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<ApiErrorBody>({});
  // Set only by the duplicate-email flip, so the shopper knows why the form changed
  // under them; a manual toggle to the login form needs no explanation.
  const [notice, setNotice] = useState<string | null>(null);
  // Counts completed submits — the Turnstile reset signal. Tokens are single-use,
  // so a failed attempt must hand the shopper a fresh one. (On success the step
  // unmounts, so the extra reset there is moot.)
  const [attempts, setAttempts] = useState(0);

  /** Body helper: attach the widget token when one exists; with the widget off or
   * blocked, keep the exact old body shape and let Django decide. */
  function withTurnstile(body: Record<string, unknown>): Record<string, unknown> {
    const token = turnstileToken();
    return token ? { ...body, turnstile_token: token } : body;
  }

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
      setPhase("login");
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot mount check only
  }, []);

  /** Runs after a successful register/login AND after the mount me-check. The
   * me-check path is load-bearing for guest Buy Now: the guest is sent to the
   * standalone /login page (intent stashed), so by the time checkout mounts they
   * are already signed in and THIS is the only place the intent gets resumed.
   *
   * The guest-cart merge USED to live here, snapshotting `cart.id` before the auth
   * call. It now happens server-side inside the auth BFF's login/register actions,
   * for two reasons: it belongs to authenticating rather than to checkout (the
   * Plan-15 /login and /register pages would each have had to remember it), and the
   * client snapshot had a race — `cart.id` comes from react-query, so a shopper who
   * submitted before that query resolved merged nothing at all. The cookie the BFF
   * reads has no such race. Do NOT reintroduce a merge call here.
   *
   * The Buy-Now resume stays client-side: the intent lives in sessionStorage, which
   * the server cannot see. Best-effort — a failure must never block checkout, and the
   * item may already be in the cart. The invalidate below covers the server-side
   * merge as well, so the refetched cart reflects both. */
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
      }
    }
    queryClient.invalidateQueries({ queryKey: ["cart"] });
    complete(1, { userEmail });
  }

  function looksLikeDuplicateEmail(body: ApiErrorBody): boolean {
    return Array.isArray(body.email) && body.email.some((m) => /already exists/i.test(m));
  }

  function switchPhase(next: Phase) {
    setPhase(next);
    setPassword("");
    setFormError(null);
    setFieldErrors({});
    setNotice(null);
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
        body: JSON.stringify(withTurnstile({
          email, password, first_name: firstName,
          phone, ...(whatsapp ? { whatsapp } : {}),
        })),
      });
      if (res.ok) {
        await runPostAuth(email);
        return;
      }
      const body: ApiErrorBody = await res.json().catch(() => ({}));
      if (res.status === 400 && looksLikeDuplicateEmail(body)) {
        switchPhase("login");
        setNotice("Good news — this email already has an account. Enter your password to continue.");
        return;
      }
      setFieldErrors(body);
      if (body.detail) setFormError(body.detail);
      else if (!body.email && !body.password && !body.first_name && !body.phone && !body.whatsapp) {
        setFormError("Something went wrong creating your account — please try again.");
      }
    } catch {
      setFormError("Something went wrong creating your account — please try again.");
    } finally {
      setSubmitting(false);
      setAttempts((a) => a + 1);
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
        body: JSON.stringify(withTurnstile({ email, password })),
      });
      if (res.ok) {
        await runPostAuth(email);
        return;
      }
      const body: ApiErrorBody = await res.json().catch(() => ({}));
      setFormError(body.detail ?? "We couldn't sign you in — check your email and password.");
    } catch {
      setFormError("Something went wrong signing you in — please try again.");
    } finally {
      setSubmitting(false);
      setAttempts((a) => a + 1);
    }
  }

  if (phase === "checking") {
    return <p className="text-sm text-muted">Checking your account…</p>;
  }

  if (phase === "login") {
    return (
      <form onSubmit={submitLogin} className="space-y-4" noValidate>
        {notice && <p className="text-sm text-muted">{notice}</p>}
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
            inputMode="email"
            autoCapitalize="none"
            spellCheck={false}
            className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
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
        <TurnstileWidget resetSignal={attempts} />
        <button
          type="submit"
          disabled={submitting || !email || !password}
          className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
        <p className="text-sm text-muted">
          New to Toke Cosmetics?{" "}
          <button
            type="button"
            onClick={() => switchPhase("register")}
            className="underline hover:text-foreground"
          >
            Create an account
          </button>
          {" · "}
          <Link href="/forgot-password" className="underline hover:text-foreground">
            Forgot password?
          </Link>
        </p>
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
      <div>
        {/* `phone` holds E.164 ("" while invalid) — it gates the submit button, so a
            half-typed number reads as "not filled in yet", matching the other gates. */}
        <PhoneField
          id="signin-phone"
          name="phone"
          label="Phone number"
          defaultCountry={cart.country}
          required
          onValueChange={setPhone}
        />
        {fieldErrors.phone && (
          <p role="alert" className="mt-1 text-sm text-red-700">
            {fieldErrors.phone.join(" ")}
          </p>
        )}
      </div>
      <div>
        <PhoneField
          id="signin-whatsapp"
          name="whatsapp"
          label="WhatsApp number"
          defaultCountry={cart.country}
          onValueChange={setWhatsapp}
          hint="For order updates on WhatsApp. Can be the same as your phone number."
        />
        {fieldErrors.whatsapp && (
          <p role="alert" className="mt-1 text-sm text-red-700">
            {fieldErrors.whatsapp.join(" ")}
          </p>
        )}
      </div>
      <TurnstileWidget resetSignal={attempts} />
      <button
        type="submit"
        disabled={submitting || !email || !firstName || !password || !phone}
        className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
      >
        {submitting ? "Creating account…" : "Create account"}
      </button>
      <p className="text-sm text-muted">
        Already have an account?{" "}
        <button
          type="button"
          onClick={() => switchPhase("login")}
          className="underline hover:text-foreground"
        >
          Sign in
        </button>
      </p>
    </form>
  );
}
