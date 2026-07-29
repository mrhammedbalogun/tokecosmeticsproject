"use client";

/**
 * The second-factor screen: enrolment, verification and the recovery-code path, in one
 * component because they are one decision from the staff member's point of view — "I have
 * my phone" / "I do not".
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
 * They exist in exactly one HTTP response. The confirm action therefore returns them
 * instead of redirecting, and the staff member continues by hand. Redirecting past them
 * would silently throw away the only copy.
 */
import { useActionState, useMemo } from "react";
import { useFormStatus } from "react-dom";
import { encode } from "uqr";
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
