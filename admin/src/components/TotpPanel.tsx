"use client";

/**
 * The second-factor screen: enrolment, verification and the recovery-code path, in one
 * component because they are one decision from the staff member's point of view — "I have
 * my phone" / "I do not".
 *
 * ── WHY THERE IS NO QR CODE ───────────────────────────────────────────────────────
 *
 * Rendering one needs a QR encoder, and this app is allowed new dependencies only where
 * the storefront already uses the equivalent. The storefront has none, so the setup screen
 * shows the key for MANUAL ENTRY, which every authenticator app supports, plus the raw
 * `otpauth://` URI for anyone who wants to paste it. This is reported upward as a
 * dependency question rather than solved by hand-rolling Reed-Solomon in a security flow,
 * and NOT solved by pointing an <img> at a QR-generating web service — that would put the
 * TOTP secret in a third party's request log, which is the whole factor, given away.
 *
 * ── THE RECOVERY CODES ARE SHOWN ONCE ─────────────────────────────────────────────
 *
 * They exist in exactly one HTTP response. The confirm action therefore returns them
 * instead of redirecting, and the staff member continues by hand. Redirecting past them
 * would silently throw away the only copy.
 */
import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import type { ConfirmState, EnrolState, RecoveryState } from "@/app/totp/actions";

function Submit({ label, busy }: { label: string; busy: string }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="mt-4 w-full rounded-md bg-accent px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
    >
      {pending ? busy : label}
    </button>
  );
}

function Alert({ children }: { children: React.ReactNode }) {
  return (
    <p
      role="alert"
      className="mb-4 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger"
    >
      {children}
    </p>
  );
}

const CODE_INPUT =
  "mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 font-mono text-sm tracking-[0.3em] outline-none focus:border-accent";

export interface TotpPanelProps {
  next: string;
  setup: boolean;
  recovery: boolean;
  enrolAction: (prev: EnrolState, fd: FormData) => Promise<EnrolState>;
  confirmAction: (prev: ConfirmState, fd: FormData) => Promise<ConfirmState>;
  recoveryAction: (prev: RecoveryState, fd: FormData) => Promise<RecoveryState>;
}

export function TotpPanel(props: TotpPanelProps) {
  const [enrol, runEnrol] = useActionState<EnrolState, FormData>(props.enrolAction, {});
  const [confirm, runConfirm] = useActionState<ConfirmState, FormData>(props.confirmAction, {
    next: props.next,
  });
  const [recover, runRecover] = useActionState<RecoveryState, FormData>(
    props.recoveryAction,
    {},
  );

  if (confirm.recoveryCodes?.length) {
    return <RecoveryCodes codes={confirm.recoveryCodes} next={confirm.next ?? props.next} />;
  }

  if (props.recovery) {
    return (
      <div>
        <h2 className="text-base font-semibold">Use a recovery code</h2>
        <p className="mt-1 text-sm text-muted">
          Enter one of the codes you saved when you set up two-factor authentication. It
          can be used once, and it will remove the authenticator you have now — you will be
          asked to set up a new one straight away.
        </p>
        <form action={runRecover} className="mt-4">
          {recover.error ? <Alert>{recover.error}</Alert> : null}
          <input type="hidden" name="next" value={props.next} />
          <label className="block text-sm font-medium" htmlFor="recovery-code">
            Recovery code
          </label>
          <input
            id="recovery-code"
            name="code"
            autoComplete="one-time-code"
            autoFocus
            required
            className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 font-mono text-sm outline-none focus:border-accent"
          />
          <Submit label="Use this code" busy="Checking…" />
        </form>
        <a className="mt-4 inline-block text-sm text-accent underline" href="/totp">
          Back to the code prompt
        </a>
      </div>
    );
  }

  return (
    <div>
      {props.setup ? (
        <SetupBlock enrol={enrol} runEnrol={runEnrol} />
      ) : (
        <>
          <h2 className="text-base font-semibold">Two-factor authentication</h2>
          <p className="mt-1 text-sm text-muted">
            Enter the six-digit code from your authenticator app.
          </p>
        </>
      )}

      <form action={runConfirm} className="mt-5">
        {confirm.error ? <Alert>{confirm.error}</Alert> : null}
        <input type="hidden" name="next" value={props.next} />
        <label className="block text-sm font-medium" htmlFor="code">
          Six-digit code
        </label>
        <input
          id="code"
          name="code"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          required
          className={CODE_INPUT}
        />
        <Submit label="Verify and sign in" busy="Verifying…" />
      </form>

      <p className="mt-5 border-t border-line pt-4 text-sm">
        <a className="text-accent underline" href="/totp?recovery=1">
          Lost your phone? Use a recovery code instead
        </a>
      </p>
    </div>
  );
}

function SetupBlock({
  enrol,
  runEnrol,
}: {
  enrol: EnrolState;
  runEnrol: (fd: FormData) => void;
}) {
  return (
    <div>
      <h2 className="text-base font-semibold">Set up two-factor authentication</h2>
      <p className="mt-1 text-sm text-muted">
        Every staff account needs an authenticator app. Add the key below to Google
        Authenticator, 1Password, Authy or similar, then enter the six-digit code it shows.
      </p>

      {enrol.error ? <Alert>{enrol.error}</Alert> : null}

      {enrol.enrolment ? (
        <div className="mt-4 rounded-md border border-line bg-background p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">
            Setup key
          </p>
          <p className="mt-1 break-all font-mono text-sm">{group(enrol.enrolment.secret)}</p>
          <p className="mt-3 text-xs text-muted">
            Account: {enrol.enrolment.issuer}. Type: time-based, 6 digits, 30 seconds.
          </p>
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-muted">
              Or paste this URI into your app
            </summary>
            <p className="mt-2 break-all font-mono text-[11px]">
              {enrol.enrolment.provisioning_uri}
            </p>
          </details>
          <p className="mt-3 text-xs text-warn">
            This key is shown once. If you lose it before finishing, sign in again to get a
            new one.
          </p>
        </div>
      ) : (
        <form action={runEnrol} className="mt-4">
          <Submit label="Show my setup key" busy="Generating…" />
        </form>
      )}
    </div>
  );
}

function RecoveryCodes({ codes, next }: { codes: string[]; next: string }) {
  return (
    <div>
      <h2 className="text-base font-semibold">Save your recovery codes</h2>
      <p className="mt-1 text-sm text-muted">
        These are shown once and never again. Print them or put them in a password manager.
        Each one can be used once, to sign in if you lose your phone.
      </p>
      <ul className="mt-4 grid grid-cols-2 gap-2 rounded-md border border-line bg-background p-4 font-mono text-sm">
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ul>
      <a
        href={next}
        className="mt-5 block rounded-md bg-accent px-4 py-2.5 text-center text-sm font-semibold text-white hover:bg-accent-strong"
      >
        I have saved them — continue
      </a>
    </div>
  );
}

/** Base32 in groups of four, which is how every authenticator app prints it. */
function group(secret: string): string {
  return (secret.match(/.{1,4}/g) ?? [secret]).join(" ");
}
