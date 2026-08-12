"use client";

/**
 * The second-factor screen: method choice, enrolment, verification and the
 * recovery-code path, in one component because they are one decision from the staff
 * member's point of view — "how do I prove it's me" / "I can't".
 *
 * ── THE METHOD CHOICE IS A UI STATE, NOT A PRIVILEGE ──────────────────────────────
 *
 * A fresh account (`setup`) picks between an authenticator app and email codes with a
 * plain `useState` — nothing security-relevant lives in that choice, because the
 * backend re-derives what the account may verify with on every confirm: a confirmed
 * TOTP account refuses the email method outright, and vice versa for enrolment. The
 * chooser RECOMMENDS the authenticator on the card itself, because email codes are
 * exactly as strong as the staff member's inbox and the UI should say so once, at the
 * moment of choice, rather than never.
 *
 * ── THE QR CODE, AND THE LINE IT DOES NOT CROSS ───────────────────────────────────
 *
 * The QR is generated LOCALLY AND OFFLINE, in this component, from a matrix `uqr` computes
 * in memory. That adds no exposure, and the reason is worth stating precisely rather than
 * assuming: by the time this screen renders, the secret is ALREADY in the page — it
 * arrived in the enrol response and is printed a few lines below for manual entry. Drawing
 * squares from a value the page already holds reveals it to nobody new; it only saves the
 * operator from typing 32 base32 characters correctly.
 *
 * WHAT REMAINS REFUSED, permanently: anything that TRANSMITS the secret. No QR web service
 * (`<img src="https://…/qr?data=otpauth://…">` puts the second factor in a third party's
 * request log — the whole factor, given away, in a URL that is logged by default). No
 * server round-trip that could log it. No analytics on this origin at all, which is the
 * standing rule in `next.config.ts` that makes this screen safe in the first place.
 *
 * WHY `uqr` SPECIFICALLY: zero transitive dependencies (verified with `npm ls --all`, a
 * flat leaf), ~79 KB, and its bundle contains no `fetch`, no `XMLHttpRequest`, no
 * `WebSocket`, no node `http`/`net`/`fs` import, no `eval` and no `new Function` (verified
 * by grep, not assumed). It cannot phone home because it has nothing to phone home with.
 *
 * WHY `encode()` AND NOT `renderSVG()`: the matrix is turned into React `<rect>` elements
 * below. That avoids `dangerouslySetInnerHTML`, avoids a `data:` URI, and avoids an inline
 * `<style>` — so the origin's CSP needed no widening whatsoever to accommodate this.
 *
 * ── THE MANUAL FALLBACK IS NOT OPTIONAL ───────────────────────────────────────────
 *
 * The grouped base32 key and the raw `otpauth://` URI stay visible ALONGSIDE the QR, and
 * `__tests__/TotpPanel.test.tsx` asserts both survive together. A QR is useless on a
 * desktop-only setup, on a phone with camera permission denied, and to anyone using a
 * screen reader — and `docs/runbooks/admin-gate.md` §6 assumes throughout that a human can
 * always fall back to typing. A future refactor that "tidies away" the key would break the
 * recovery story silently.
 *
 * ── THE RECOVERY CODES ARE SHOWN ONCE ─────────────────────────────────────────────
 *
 * They exist in exactly one HTTP response — the one that confirms an enrolment, by
 * either method. The confirm action therefore returns them instead of redirecting, and
 * the staff member continues by hand. Redirecting past them would silently throw away
 * the only copy.
 *
 * ── "DON'T ASK AGAIN ON THIS DEVICE" ──────────────────────────────────────────────
 *
 * A checkbox on both code forms, off by default. Ticking it asks Django for a 30-day
 * trust token alongside the session; the BFF stores it as an httpOnly cookie and later
 * logins redeem it INSIDE the same confirm endpoint a code would go to — the password
 * step never gets faster, only the code prompt disappears. The label says the honest
 * thing ("this device"), and the setup screens leave it available too: the person who
 * just enrolled on their own laptop is exactly who wants it.
 */
import { useActionState, useMemo, useState } from "react";
import { useFormStatus } from "react-dom";
import { encode } from "uqr";
import type {
  ConfirmState,
  EmailOtpState,
  EnrolState,
  RecoveryState,
} from "@/app/totp/actions";

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

export type PanelMethod = "totp" | "email";

export interface TotpPanelProps {
  next: string;
  setup: boolean;
  /** The method the account already confirmed, from the login response; null during
   *  setup (nothing confirmed yet) — the chooser decides. */
  method: PanelMethod | null;
  recovery: boolean;
  enrolAction: (prev: EnrolState, fd: FormData) => Promise<EnrolState>;
  confirmAction: (prev: ConfirmState, fd: FormData) => Promise<ConfirmState>;
  recoveryAction: (prev: RecoveryState, fd: FormData) => Promise<RecoveryState>;
  emailOtpAction: () => Promise<EmailOtpState>;
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
  // Setup only: which card the person picked. Chosen fresh on every visit — the
  // backend is the memory of what actually got confirmed.
  const [picked, setPicked] = useState<PanelMethod | null>(null);

  if (confirm.recoveryCodes?.length) {
    return <RecoveryCodes codes={confirm.recoveryCodes} next={confirm.next ?? props.next} />;
  }

  if (props.recovery) {
    return (
      <div>
        <h2 className="text-base font-semibold">Use a recovery code</h2>
        <p className="mt-1 text-sm text-muted">
          Enter one of the codes you saved when you set up two-factor authentication. It
          can be used once, and it will remove your current second factor and any trusted
          devices — you will be asked to set up again straight away.
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

  // Which method the code form below should verify. Ordinary login: whatever the
  // account confirmed. Setup: whatever was just picked.
  const active: PanelMethod = props.setup ? (picked ?? "totp") : (props.method ?? "totp");

  if (props.setup && picked === null) {
    return <MethodChooser onPick={setPicked} />;
  }

  return (
    <div>
      {props.setup ? (
        active === "totp" ? (
          <SetupBlock enrol={enrol} runEnrol={runEnrol} onBack={() => setPicked(null)} />
        ) : (
          <EmailBlock
            setup
            emailOtpAction={props.emailOtpAction}
            onBack={() => setPicked(null)}
          />
        )
      ) : active === "totp" ? (
        <>
          <h2 className="text-base font-semibold">Two-factor authentication</h2>
          <p className="mt-1 text-sm text-muted">
            Enter the six-digit code from your authenticator app.
          </p>
        </>
      ) : (
        <EmailBlock setup={false} emailOtpAction={props.emailOtpAction} />
      )}

      <form action={runConfirm} className="mt-5">
        {confirm.error ? <Alert>{confirm.error}</Alert> : null}
        <input type="hidden" name="next" value={props.next} />
        <input type="hidden" name="method" value={active} />
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
        <label className="mt-3 flex items-start gap-2 text-sm">
          <input type="checkbox" name="trust_device" className="mt-0.5 accent-accent" />
          <span>
            Don&apos;t ask for a code on this device for 30 days
            <span className="block text-xs text-muted">
              Only on your own computer — you&apos;ll still enter your password every time.
            </span>
          </span>
        </label>
        <Submit label="Verify and sign in" busy="Verifying…" />
      </form>

      <p className="mt-5 border-t border-line pt-4 text-sm">
        <a className="text-accent underline" href="/totp?recovery=1">
          Can&apos;t get a code? Use a recovery code instead
        </a>
      </p>
    </div>
  );
}

function MethodChooser({ onPick }: { onPick: (m: PanelMethod) => void }) {
  const card =
    "w-full rounded-md border border-line bg-surface p-4 text-left transition-colors hover:border-accent";
  return (
    <div>
      <h2 className="text-base font-semibold">Set up two-factor authentication</h2>
      <p className="mt-1 text-sm text-muted">
        Every staff account needs a second factor. Choose how you want to prove it&apos;s
        you when you sign in.
      </p>
      <div className="mt-4 grid gap-3">
        <button type="button" className={card} onClick={() => onPick("totp")}>
          <span className="block text-sm font-semibold">
            Authenticator app{" "}
            <span className="rounded bg-accent/10 px-1.5 py-0.5 text-xs font-medium text-accent">
              Recommended
            </span>
          </span>
          <span className="mt-1 block text-xs text-muted">
            Codes from Google Authenticator, 1Password, Authy or similar. Works offline
            and is the strongest option — it never leaves your phone.
          </span>
        </button>
        <button type="button" className={card} onClick={() => onPick("email")}>
          <span className="block text-sm font-semibold">Email codes</span>
          <span className="mt-1 block text-xs text-muted">
            A six-digit code sent to your staff email at each sign-in. Only as safe as
            your inbox — pick the app if you can.
          </span>
        </button>
      </div>
    </div>
  );
}

/**
 * The email-code screen, shared by setup and ordinary login: a send/resend button and
 * the explanation. The code FORM stays in the parent so both methods share one form,
 * one error state and one trust checkbox.
 *
 * Sending is a deliberate click rather than an automatic effect on mount: an effect
 * would fire again on every re-render dance React chooses to do, and although the
 * backend's cooldown makes that harmless, a button also gives the person a resend
 * control and a truthful "sent" state for free.
 */
function EmailBlock({
  setup,
  emailOtpAction,
  onBack,
}: {
  setup: boolean;
  emailOtpAction: () => Promise<EmailOtpState>;
  onBack?: () => void;
}) {
  const [state, run] = useActionState<EmailOtpState, FormData>(
    async () => emailOtpAction(),
    {},
  );
  return (
    <div>
      <h2 className="text-base font-semibold">
        {setup ? "Set up email codes" : "Two-factor authentication"}
      </h2>
      <p className="mt-1 text-sm text-muted">
        {setup
          ? "We'll email a six-digit code to your staff address. Entering it turns email codes on and finishes signing you in."
          : "We'll email a six-digit code to your staff address."}
      </p>

      {state.error ? <div className="mt-3"><Alert>{state.error}</Alert></div> : null}

      <form action={run} className="mt-3">
        <SendButton sent={Boolean(state.sent)} />
      </form>
      {state.sent ? (
        <p className="mt-2 text-xs text-muted" role="status">
          {state.retryAfter && !setup
            ? "Your code is on its way — check your inbox and spam folder."
            : "Code sent — check your inbox and spam folder."}
        </p>
      ) : null}
      {onBack ? (
        <button
          type="button"
          onClick={onBack}
          className="mt-3 text-xs text-accent underline"
        >
          Choose a different method
        </button>
      ) : null}
    </div>
  );
}

function SendButton({ sent }: { sent: boolean }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="w-full rounded-md border border-line bg-surface px-4 py-2.5 text-sm font-semibold transition-colors hover:border-accent disabled:opacity-60"
    >
      {pending ? "Sending…" : sent ? "Resend code" : "Email me a code"}
    </button>
  );
}

function SetupBlock({
  enrol,
  runEnrol,
  onBack,
}: {
  enrol: EnrolState;
  runEnrol: (fd: FormData) => void;
  onBack?: () => void;
}) {
  return (
    <div>
      <h2 className="text-base font-semibold">Set up your authenticator app</h2>
      <p className="mt-1 text-sm text-muted">
        Add the key below to Google Authenticator, 1Password, Authy or similar, then
        enter the six-digit code it shows.
      </p>

      {enrol.error ? <Alert>{enrol.error}</Alert> : null}

      {enrol.enrolment ? (
        <div className="mt-4 rounded-md border border-line bg-background p-4">
          <QrCode value={enrol.enrolment.provisioning_uri} />

          <p className="mt-4 text-xs text-muted">
            Can&apos;t scan it? Enter this key by hand instead — every authenticator app
            accepts one.
          </p>
          <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-muted">
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
      {onBack && !enrol.enrolment ? (
        <button
          type="button"
          onClick={onBack}
          className="mt-3 text-xs text-accent underline"
        >
          Choose a different method
        </button>
      ) : null}
    </div>
  );
}

function RecoveryCodes({ codes, next }: { codes: string[]; next: string }) {
  return (
    <div>
      <h2 className="text-base font-semibold">Save your recovery codes</h2>
      <p className="mt-1 text-sm text-muted">
        These are shown once and never again. Print them or put them in a password manager.
        Each one can be used once, to sign in if you lose access to your second factor.
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

/**
 * The `otpauth://` URI as a scannable QR, computed in this process and drawn as SVG rects.
 *
 * `border: 4` is the quiet zone the QR spec requires. It is not padding for looks — most
 * scanners fail to lock on without it, and `uqr`'s default of 1 is too small.
 *
 * `ecc: "M"` rather than the default "L": medium error correction survives screen glare,
 * an odd angle and a low-DPI monitor, which is the realistic condition here. It costs a
 * slightly denser code and nothing else.
 *
 * ── WHY IT IS NOT ONE RECT PER MODULE ─────────────────────────────────────────────
 *
 * A version-5 code with a quiet zone is ~47x47, so the naive rendering is a couple of
 * thousand DOM nodes. Consecutive dark modules in a row are merged into a single rect,
 * which typically cuts that by an order of magnitude. `shapeRendering="crispEdges"` turns
 * antialiasing off — a blurred module boundary is exactly what makes a scanner give up.
 *
 * ── ACCESSIBILITY ─────────────────────────────────────────────────────────────────
 *
 * `role="img"` with a label that does NOT contain the secret (an `aria-label` is read
 * aloud, and reading a TOTP secret aloud in an open-plan office is its own problem). The
 * genuinely accessible path is the manual key below it, which is why that must never be
 * removed.
 */
function QrCode({ value }: { value: string }) {
  // Recomputed only when the URI changes; the enrol response arrives once per enrolment.
  const rows = useMemo(() => {
    const { size, data } = encode(value, { border: 4, ecc: "M" });
    // Run-length merge per row -> [x, y, width] triples.
    const runs: Array<[number, number, number]> = [];
    for (let y = 0; y < size; y++) {
      let x = 0;
      while (x < size) {
        if (!data[y][x]) {
          x++;
          continue;
        }
        const start = x;
        while (x < size && data[y][x]) x++;
        runs.push([start, y, x - start]);
      }
    }
    return { size, runs };
  }, [value]);

  return (
    <svg
      viewBox={`0 0 ${rows.size} ${rows.size}`}
      shapeRendering="crispEdges"
      role="img"
      aria-label="QR code for your authenticator app"
      className="mx-auto block h-44 w-44 bg-white"
    >
      {rows.runs.map(([x, y, width]) => (
        <rect key={`${x}-${y}`} x={x} y={y} width={width} height={1} fill="#000000" />
      ))}
    </svg>
  );
}
