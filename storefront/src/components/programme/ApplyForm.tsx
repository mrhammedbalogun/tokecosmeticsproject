"use client";

/**
 * The Student Entrepreneurship Program's application form.
 *
 * ── STATE IS DELIBERATELY NOT `useActionState` ──────────────────────────────────────
 *
 * Most forms in this app are Server Function forms. This one posts straight to Django
 * (see `lib/entrepreneurship.ts` for the throttle-key reason), so it is a plain
 * controlled form with its own submit state — and because of that, `required` and
 * `type=email` stay on the inputs so the browser's own validation runs first, offline
 * and before hydration.
 *
 * ── THE FORM IS NOT CLEARED ON FAILURE ──────────────────────────────────────────────
 *
 * Every field is uncontrolled and lives in the DOM, so a refused submit leaves all of it
 * exactly where the student typed it. That is the whole point on a nine-field form filled
 * on a phone: the failure they will actually hit is the phone-number rule, and a form
 * that empties itself over one field is a form that gets abandoned.
 *
 * A Turnstile token, by contrast, is single-use: `attempt` is bumped on every failure so
 * the widget mints a fresh one, or the second try fails as a duplicate.
 */
import { useId, useState } from "react";
import Link from "next/link";
import { TurnstileWidget, turnstileToken } from "@/components/auth/TurnstileWidget";
import { PhoneField } from "@/components/ui/PhoneField";
import {
  ACADEMIC_LEVELS,
  ApplyError,
  MOTIVATION_MAX,
  submitApplication,
  type ProgrammeConfig,
} from "@/lib/entrepreneurship";

const inputClass =
  "w-full rounded-[var(--radius-card)] border border-line bg-surface px-3 py-2.5 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:opacity-60";

export function ApplyForm({ config }: { config: ProgrammeConfig }) {
  const formId = useId();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  // Set when the backend answers 409: the intake closed between this page being built
  // and this submit. Rendered as the closed state rather than as a field error, because
  // it is not something the student can fix by editing anything.
  const [closedNow, setClosedNow] = useState<string | null>(null);
  // Bumped on every failure: it is what makes Turnstile hand out a fresh single-use
  // token, and what re-announces the error to a screen reader on a repeat failure.
  const [attempt, setAttempt] = useState(0);
  const [motivation, setMotivation] = useState("");

  // The phone picker defaults to whichever country is chosen above it. Tracked in state
  // for that one reason — a Nigerian student who picks Nigeria should not then have to
  // find +234 in a list of two hundred.
  const [country, setCountry] = useState(config.countries[0]?.code ?? "NG");

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    const data = new FormData(event.currentTarget);
    setBusy(true);
    setMessage(null);
    setFieldErrors({});

    try {
      await submitApplication({
        country: String(data.get("country") ?? ""),
        full_name: String(data.get("full_name") ?? "").trim(),
        email: String(data.get("email") ?? "").trim(),
        // PhoneField submits E.164 through a hidden input; the visible one carries no
        // name, so this is always the diallable form or "".
        phone: String(data.get("phone") ?? "").trim(),
        institution: String(data.get("institution") ?? "").trim(),
        academic_level: String(data.get("academic_level") ?? "").trim(),
        course_of_study: String(data.get("course_of_study") ?? "").trim(),
        social_handle: String(data.get("social_handle") ?? "").trim(),
        motivation: motivation.trim(),
        website: String(data.get("website") ?? ""),
        turnstile_token: turnstileToken(),
      });
      setDone(true);
    } catch (error) {
      setAttempt((n) => n + 1);
      if (error instanceof ApplyError) {
        if (error.intakeClosed) {
          setClosedNow(error.message);
        } else {
          setMessage(error.message);
          setFieldErrors(error.fieldErrors);
        }
      } else {
        setMessage("We could not send your application. Try again in a moment.");
      }
    } finally {
      setBusy(false);
    }
  }

  if (done) return <Success />;
  if (closedNow) return <IntakeClosed message={closedNow} />;

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      {message && (
        <p
          // `key` on the attempt so a repeated identical message is re-announced rather
          // than skipped as unchanged text.
          key={attempt}
          role="alert"
          className="rounded-[var(--radius-card)] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {message}
        </p>
      )}

      <div className="grid gap-5 sm:grid-cols-2">
        <Field
          id={`${formId}-name`}
          name="full_name"
          label="Full name"
          autoComplete="name"
          required
          disabled={busy}
          error={fieldErrors.full_name}
        />

        <div>
          <label
            htmlFor={`${formId}-country`}
            className="block text-sm font-medium text-foreground"
          >
            Country you study in
          </label>
          <select
            id={`${formId}-country`}
            name="country"
            required
            disabled={busy}
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className={`${inputClass} mt-1.5`}
          >
            {config.countries.map((option) => (
              <option key={option.code} value={option.code}>
                {option.name}
              </option>
            ))}
          </select>
          {fieldErrors.country && <FieldError>{fieldErrors.country}</FieldError>}
        </div>

        <Field
          id={`${formId}-email`}
          name="email"
          type="email"
          label="Email address"
          autoComplete="email"
          required
          disabled={busy}
          error={fieldErrors.email}
          hint="We reply to this address."
        />

        <div>
          {/* `key` on the country so the picker re-initialises when the market above
              changes. Without it the flag stays on whatever it was first mounted with,
              and every non-Nigerian applicant has to find their dial code by hand.

              THE COST, STATED: remounting clears anything already typed here. That is
              the right way round — the country select sits two fields ABOVE this one and
              defaults to the market most applicants are in, so "change the country after
              typing the number" is a rare sequence, while "picked the UK and got +234"
              would be every single non-NG applicant, every time. */}
          <PhoneField
            key={country}
            id={`${formId}-phone`}
            name="phone"
            label="Phone number"
            required
            defaultCountry={country}
            hint="WhatsApp number is best — it is how we will reach you."
          />
          {fieldErrors.phone && <FieldError>{fieldErrors.phone}</FieldError>}
        </div>

        <Field
          id={`${formId}-institution`}
          name="institution"
          label="University / Polytechnic / College"
          autoComplete="organization"
          required
          disabled={busy}
          error={fieldErrors.institution}
          className="sm:col-span-2"
        />

        <div>
          <label
            htmlFor={`${formId}-level`}
            className="block text-sm font-medium text-foreground"
          >
            Current academic level
          </label>
          {/* A `<datalist>`, NOT a `<select>`. "300 Level" is Nigerian, "Year 2" is
              British and "Sophomore" is American, and this programme runs in four
              markets — a fixed list would either enumerate every education system or
              refuse a real student, and refusing a real student on a marketing form is
              the expensive error. The suggestions cover the common Nigerian answers, so
              most applicants still never type. */}
          <input
            id={`${formId}-level`}
            name="academic_level"
            list={`${formId}-levels`}
            required
            disabled={busy}
            placeholder="e.g. 300 Level"
            aria-invalid={fieldErrors.academic_level ? true : undefined}
            className={`${inputClass} mt-1.5 ${fieldErrors.academic_level ? "border-red-300" : ""}`}
          />
          <datalist id={`${formId}-levels`}>
            {ACADEMIC_LEVELS.map((level) => (
              <option key={level} value={level} />
            ))}
          </datalist>
          {fieldErrors.academic_level && (
            <FieldError>{fieldErrors.academic_level}</FieldError>
          )}
        </div>

        <Field
          id={`${formId}-course`}
          name="course_of_study"
          label="Course of study"
          required
          disabled={busy}
          error={fieldErrors.course_of_study}
        />

        <Field
          id={`${formId}-social`}
          name="social_handle"
          label="Instagram, TikTok or WhatsApp TV"
          optional
          disabled={busy}
          error={fieldErrors.social_handle}
          hint="Where you already post. It helps — it is not required."
          className="sm:col-span-2"
        />
      </div>

      <div>
        <label
          htmlFor={`${formId}-motivation`}
          className="block text-sm font-medium text-foreground"
        >
          Why do you want to join?{" "}
          <span className="font-normal text-muted">(optional)</span>
        </label>
        <textarea
          id={`${formId}-motivation`}
          name="motivation"
          rows={5}
          maxLength={MOTIVATION_MAX}
          disabled={busy}
          value={motivation}
          onChange={(e) => setMotivation(e.target.value)}
          placeholder="Tell us how you would sell, and who you would sell to. A few lines is plenty."
          className={`${inputClass} mt-1.5 resize-y`}
        />
        <div className="mt-1 flex justify-between text-xs text-muted">
          <span>{fieldErrors.motivation ?? "A short paragraph is plenty."}</span>
          {/* Only once it is worth knowing about — a counter from character one reads as
              a minimum to reach. */}
          {motivation.length > MOTIVATION_MAX - 300 && (
            <span className="tabular-nums">
              {MOTIVATION_MAX - motivation.length} left
            </span>
          )}
        </div>
      </div>

      {/* THE HONEYPOT. Off-screen rather than `display:none` — some bots skip hidden
          fields specifically — and `tabIndex={-1}` plus `aria-hidden` keep it away from
          both keyboard and screen-reader users. The backend answers a filled one with
          201 and stores nothing, so a bot is never told it failed. */}
      <div aria-hidden className="absolute left-[-9999px] top-0 h-0 w-0 overflow-hidden">
        <label htmlFor={`${formId}-website`}>Website</label>
        <input
          id={`${formId}-website`}
          name="website"
          type="text"
          tabIndex={-1}
          autoComplete="off"
        />
      </div>

      <TurnstileWidget resetSignal={attempt} />

      <button
        type="submit"
        disabled={busy}
        className="w-full rounded-full bg-accent px-6 py-3.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-70 sm:w-auto sm:px-12"
      >
        {busy ? "Sending your application…" : "Apply to the programme"}
      </button>

      <p className="text-xs leading-relaxed text-muted">
        We use what you send here to consider you for the programme and to contact you
        about it. Your details are never sold or shared. Email{" "}
        <a
          href="mailto:info@tokecosmetics.com"
          className="underline underline-offset-2"
        >
          info@tokecosmetics.com
        </a>{" "}
        to ask us to delete them.{" "}
        <strong className="font-medium text-foreground">
          Joining is free — we will never ask you to pay to take part.
        </strong>
      </p>
    </form>
  );
}

function Success() {
  return (
    <div
      role="status"
      className="rounded-[var(--radius-card)] border border-accent/30 bg-accent/5 p-8 text-center sm:p-10"
    >
      <div
        className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-accent text-white"
        aria-hidden
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          className="h-6 w-6"
        >
          <path d="m5 13 4 4L19 7" />
        </svg>
      </div>
      <h3 className="mt-5 font-display text-2xl text-foreground">Application received</h3>
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted">
        Thank you — we have your application, and a confirmation is on its way to your
        inbox.
      </p>
      {/* DELIBERATELY NO DEADLINE. One person reads these; a promise of "within 5 days"
          in an automated message is a complaint waiting to arrive. */}
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted">
        We read every application ourselves. If you look like a good fit, someone from
        our team will contact you on the number you gave us to talk it through.
      </p>
      <p className="mx-auto mt-4 max-w-md text-xs leading-relaxed text-muted">
        We will never ask you to pay anything to join. If a message asks you for a fee, it
        did not come from us.
      </p>
      <Link
        href="/products"
        className="mt-6 inline-block text-sm font-medium text-accent underline underline-offset-4"
      >
        Have a look at what you would be selling
      </Link>
    </div>
  );
}

/** The intake closed between this page being built and this submit landing.
 *
 *  Its own state rather than a red error banner: nothing the student typed is wrong, and
 *  telling them to "check the highlighted fields" when there is nothing to fix is how a
 *  form makes somebody try four more times. */
function IntakeClosed({ message }: { message: string }) {
  return (
    <div
      role="status"
      className="rounded-[var(--radius-card)] border border-line bg-beige p-8 text-center sm:p-10"
    >
      <h3 className="font-display text-2xl text-foreground">
        Applications just closed
      </h3>
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted">{message}</p>
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted">
        Your details were not submitted — nothing was lost at your end, and nothing was
        saved at ours.
      </p>
    </div>
  );
}

function Field({
  id,
  name,
  label,
  type = "text",
  required,
  optional,
  disabled,
  autoComplete,
  hint,
  error,
  className,
}: {
  id: string;
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  optional?: boolean;
  disabled?: boolean;
  autoComplete?: string;
  hint?: string;
  error?: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-sm font-medium text-foreground">
        {label}
        {optional && <span className="font-normal text-muted"> (optional)</span>}
      </label>
      <input
        id={id}
        name={name}
        type={type}
        required={required}
        disabled={disabled}
        autoComplete={autoComplete}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={`${inputClass} mt-1.5 ${error ? "border-red-300" : ""}`}
      />
      {error ? (
        <FieldError id={`${id}-error`}>{error}</FieldError>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1 text-xs text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function FieldError({ id, children }: { id?: string; children: React.ReactNode }) {
  return (
    <p id={id} className="mt-1 text-xs text-red-600">
      {children}
    </p>
  );
}
