"use client";

/**
 * Profile editor, following LoginForm's conventions (pending/error state client-side,
 * Server Function submit, native validation on, live region from first paint). Email
 * is read-only upstream (MeSerializer) so it renders as text, not a disabled input a
 * user would fight with.
 */
import { useActionState } from "react";
import type { ProfileState } from "@/app/(shop)/account/profile/actions";
import { PhoneField } from "@/components/ui/PhoneField";

const ERROR_ID = "profile-error";

const inputClass =
  "w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-accent/40";

export interface ProfileDefaults {
  email: string;
  first_name: string;
  last_name: string;
  phone: string;
  whatsapp: string;
  marketing_consent: boolean;
}

export function ProfileForm({
  defaults,
  action,
  initialState = {},
}: {
  defaults: ProfileDefaults;
  action: (state: ProfileState, formData: FormData) => Promise<ProfileState>;
  initialState?: ProfileState;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const error = state.error;

  return (
    <form action={formAction} className="max-w-md space-y-4">
      <div aria-live="polite">
        {error && (
          <p id={ERROR_ID} role="alert" className="text-sm text-red-700">
            {error}
          </p>
        )}
        {state.saved && !error && (
          <p className="text-sm text-accent-strong">Profile saved.</p>
        )}
      </div>

      <div>
        <span className="mb-1 block text-sm font-medium">Email</span>
        <p className="text-sm text-muted">{defaults.email}</p>
      </div>

      <div>
        <label htmlFor="profile-first-name" className="mb-1 block text-sm font-medium">
          First name
        </label>
        <input
          id="profile-first-name"
          name="first_name"
          type="text"
          defaultValue={defaults.first_name}
          required
          autoComplete="given-name"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? ERROR_ID : undefined}
          className={inputClass}
        />
      </div>

      <div>
        <label htmlFor="profile-last-name" className="mb-1 block text-sm font-medium">
          Last name
        </label>
        <input
          id="profile-last-name"
          name="last_name"
          type="text"
          defaultValue={defaults.last_name}
          autoComplete="family-name"
          className={inputClass}
        />
      </div>

      {/* Not `required`, unlike registration: accounts that predate the phone field
          would otherwise be unable to save any profile edit until they add one. */}
      <PhoneField
        id="profile-phone"
        name="phone"
        label="Phone"
        defaultValue={defaults.phone}
        autoComplete="tel"
      />

      <PhoneField
        id="profile-whatsapp"
        name="whatsapp"
        label="WhatsApp"
        defaultValue={defaults.whatsapp}
        autoComplete="tel"
        hint="For order updates on WhatsApp. Can be the same as your phone number."
      />

      <label htmlFor="profile-consent" className="flex items-start gap-2 text-sm">
        <input
          id="profile-consent"
          name="marketing_consent"
          type="checkbox"
          defaultChecked={defaults.marketing_consent}
          className="mt-0.5"
        />
        <span>Email me about new products and offers (marketing)</span>
      </label>

      <button
        type="submit"
        disabled={pending}
        className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
      >
        {pending ? "Saving…" : "Save changes"}
      </button>
    </form>
  );
}
