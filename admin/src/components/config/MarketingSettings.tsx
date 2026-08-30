"use client";

/**
 * The Marketing screen (Plan-44): one master switch, then a card per ad platform.
 *
 * The layout follows the Tax screen next door for the same reasons. The master switch
 * saves IMMEDIATELY, because a switch that needs a second click will be left
 * half-flipped. The per-channel cards have an explicit Save, because a pixel id is
 * pasted and saving keystrokes as they happen would write half an ID.
 *
 * ── WHAT THIS SCREEN DELIBERATELY DOES NOT DO ───────────────────────────────────────
 *
 * It never asks for, shows, or stores a Conversions API token. Those live in the
 * server's environment; the card reports "credential set" or names the variable that is
 * missing. The cost is that switching a channel on needs an edit to `.env.prod` and a
 * restart, which the card says out loud rather than leaving Hammed to discover.
 */
import { startTransition, useState } from "react";
import {
  saveMarketingChannelAction,
  saveMarketingSettingsAction,
  sendTestEventAction,
} from "@/app/(shell)/settings/marketing/actions";
import {
  CHANNEL_BLURB,
  PIXEL_ID_LABEL,
  type MarketingChannelRow,
  type MarketingSettingsRow,
  type TestEventResult,
} from "@/lib/marketing-config";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

/** The one-line scan layer on each card: read first, edit second. */
function summary(row: MarketingChannelRow, masterOn: boolean): string {
  if (!masterOn) return "off — tracking is switched off store-wide";
  if (!row.is_enabled) return "off";
  if (!row.pixel_id) return "on, but no ID — nothing is loading";
  const halves: string[] = [];
  if (row.browser_enabled) halves.push("pixel");
  if (row.server_enabled && row.has_server_side) {
    const addressed =
      row.code !== "google_ads" || (row.server_account_id && row.server_destination_id);
    if (!addressed) halves.push("server (no destination)");
    else halves.push(row.credential_configured ? "server" : "server (no credential)");
  }
  if (halves.length === 0) return "on, but both halves are off";
  const test = row.test_event_code ? " · TEST MODE" : "";
  return `${halves.join(" + ")}${test}`;
}

export function MarketingSettings({
  settings,
  channels,
}: {
  settings: MarketingSettingsRow;
  channels: MarketingChannelRow[];
}) {
  const [masterOn, setMasterOn] = useState(settings.tracking_enabled);
  const [masterPending, setMasterPending] = useState(false);
  const [masterError, setMasterError] = useState<string | null>(null);
  const [basis, setBasis] = useState(settings.purchase_value_basis);

  const flipMaster = (next: boolean) => {
    const previous = masterOn;
    setMasterOn(next); // optimistic — snaps back if the save fails
    setMasterPending(true);
    setMasterError(null);
    startTransition(async () => {
      const state = await saveMarketingSettingsAction({ tracking_enabled: next });
      setMasterPending(false);
      if (!state.savedAt) {
        setMasterOn(previous);
        setMasterError(state.message ?? "The switch could not be saved.");
      }
    });
  };

  const changeBasis = (next: "goods" | "grand_total") => {
    const previous = basis;
    setBasis(next);
    startTransition(async () => {
      const state = await saveMarketingSettingsAction({ purchase_value_basis: next });
      if (!state.savedAt) setBasis(previous);
    });
  };

  return (
    <div className="space-y-6">
      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={masterOn}
            disabled={masterPending}
            onChange={(e) => flipMaster(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-line"
          />
          <span>
            <span className="text-sm font-medium">Measure adverts</span>
            <span className="mt-0.5 block text-xs text-muted">
              The master switch. Off means no pixel loads on the storefront, no conversion
              is sent to any platform, and the cookie banner stops being shown — there is
              nothing left to consent to.
            </span>
          </span>
        </label>
        {masterError && <p className="mt-2 text-xs text-warn">{masterError}</p>}

        <div className="mt-4 border-t border-line pt-4">
          <p className="text-sm font-medium">What a sale is worth</p>
          <p className="mt-0.5 text-xs text-muted">
            Every platform optimises against this number, so it decides which customers
            they go and find.
          </p>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            {([
              ["goods", "Net goods", "After every discount, excluding delivery and tax. What the shop actually earns."],
              ["grand_total", "Grand total", "Everything the customer was charged. Flatters ROAS; some agencies expect it."],
            ] as const).map(([value, label, blurb]) => (
              <label
                key={value}
                className={`flex-1 cursor-pointer rounded border p-3 ${
                  basis === value ? "border-accent" : "border-line"
                }`}
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  <input
                    type="radio"
                    name="purchase_value_basis"
                    checked={basis === value}
                    onChange={() => changeBasis(value)}
                    className="h-3.5 w-3.5"
                  />
                  {label}
                </span>
                <span className="mt-1 block text-xs text-muted">{blurb}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="mt-4 border-t border-line pt-4 text-xs text-muted">
          <span className="font-medium text-foreground">Consent is asked first in:</span>{" "}
          {settings.consent_required_countries.join(", ") || "nowhere"}.
          <span className="mt-1 block">
            In those countries nothing is stored and no pixel loads until the visitor
            accepts. Everywhere else the banner is shown and tracking runs until it is
            declined. Nigeria is not on the list — adding it under the NDPA is a decision,
            not a deploy.
          </span>
        </div>
      </section>

      {channels.map((channel) => (
        <ChannelCard key={channel.code} row={channel} masterOn={masterOn} />
      ))}
    </div>
  );
}

function ChannelCard({ row, masterOn }: { row: MarketingChannelRow; masterOn: boolean }) {
  const [enabled, setEnabled] = useState(row.is_enabled);
  const [pixelId, setPixelId] = useState(row.pixel_id);
  const [secondaryId, setSecondaryId] = useState(row.secondary_id);
  const [accountId, setAccountId] = useState(row.server_account_id);
  const [destinationId, setDestinationId] = useState(row.server_destination_id);
  const [browser, setBrowser] = useState(row.browser_enabled);
  const [server, setServer] = useState(row.server_enabled);
  const [testCode, setTestCode] = useState(row.test_event_code);
  const [pending, setPending] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestEventResult | null>(null);

  const save = () => {
    setPending(true);
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await saveMarketingChannelAction({
        code: row.code,
        is_enabled: enabled,
        pixel_id: pixelId,
        secondary_id: secondaryId,
        server_account_id: accountId,
        server_destination_id: destinationId,
        browser_enabled: browser,
        server_enabled: server,
        test_event_code: testCode,
      });
      setPending(false);
      if (state.savedAt) return setMessage("Saved.");
      setErrors(state.fieldErrors ?? {});
      setMessage(state.message ?? null);
    });
  };

  const sendTest = () => {
    setTesting(true);
    setTestResult(null);
    startTransition(async () => {
      setTestResult(await sendTestEventAction(row.code));
      setTesting(false);
    });
  };

  return (
    <section className="rounded-[var(--radius-card)] border border-line p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-sm font-medium">{row.label}</h2>
          <p className="mt-0.5 text-xs text-muted">{CHANNEL_BLURB[row.code]}</p>
        </div>
        <span className="text-xs text-muted">{summary({ ...row, is_enabled: enabled, pixel_id: pixelId, server_account_id: accountId, server_destination_id: destinationId, browser_enabled: browser, server_enabled: server, test_event_code: testCode }, masterOn)}</span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-xs text-muted">{PIXEL_ID_LABEL[row.code]}</span>
          <input
            className={FIELD}
            value={pixelId}
            onChange={(e) => setPixelId(e.target.value)}
            placeholder="Paste from the platform's Events Manager"
          />
          {errors.pixel_id && <span className="mt-1 block text-xs text-warn">{errors.pixel_id}</span>}
        </label>

        {row.code === "google_ads" && (
          <label className="block">
            <span className="text-xs text-muted">Conversion label</span>
            <input
              className={FIELD}
              value={secondaryId}
              onChange={(e) => setSecondaryId(e.target.value)}
              placeholder="AbC-D_efGhIjKlMn"
            />
            {errors.secondary_id && (
              <span className="mt-1 block text-xs text-warn">{errors.secondary_id}</span>
            )}
          </label>
        )}

        {row.code === "google_ads" && (
          <>
            <label className="block">
              <span className="text-xs text-muted">Customer ID (server-side)</span>
              <input
                className={FIELD}
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                placeholder="3352855298 — no dashes"
              />
              {errors.server_account_id && (
                <span className="mt-1 block text-xs text-warn">{errors.server_account_id}</span>
              )}
            </label>
            <label className="block">
              <span className="text-xs text-muted">Conversion action ID (server-side)</span>
              <input
                className={FIELD}
                value={destinationId}
                onChange={(e) => setDestinationId(e.target.value)}
                placeholder="7577766208 — the ctId= in the Ads URL"
              />
              <span className="mt-1 block text-xs text-muted">
                Must be the SAME conversion action the browser tag reports to. Google
                deduplicates on the order number; a separate “server” action double-counts
                every sale.
              </span>
            </label>
          </>
        )}

        <label className="block">
          <span className="text-xs text-muted">Test event code (optional)</span>
          <input
            className={FIELD}
            value={testCode}
            onChange={(e) => setTestCode(e.target.value)}
            placeholder="Leave blank for live"
          />
          {testCode && (
            // Every vendor says to remove this before a campaign reads the numbers, and a
            // forgotten test code is a silent zero in the ad account.
            <span className="mt-1 block text-xs text-warn">
              Events go to the platform&apos;s TEST console, not the live dataset. Clear
              this before running real adverts.
            </span>
          )}
        </label>
      </div>

      <div className="mt-4 flex flex-wrap gap-4 border-t border-line pt-3">
        <Toggle label="Switched on" checked={enabled} onChange={setEnabled} />
        <Toggle
          label="Pixel in the browser"
          checked={browser}
          onChange={setBrowser}
          hint="What the visitor's browser sends."
        />
        <Toggle
          label="Server-side events"
          checked={server}
          onChange={setServer}
          disabled={!row.has_server_side}
          hint={
            row.has_server_side
              ? "Sent from our server, so a customer who never returns from the payment page is still counted."
              : "Google Ads has no server-side upload here — it needs the Google Ads API."
          }
        />
      </div>

      {row.has_server_side && (
        <p className="mt-3 text-xs">
          {row.credential_configured ? (
            <span className="text-muted">API credential is set on the server.</span>
          ) : (
            <span className="text-warn">
              No API credential. Add{" "}
              <code className="font-mono">{row.missing_settings.join(", ")}</code> to the
              server&apos;s environment and restart — server-side events cannot be sent
              until then. (Tokens are never stored here or shown on this screen.)
            </span>
          )}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={save}
          disabled={pending}
          className="rounded bg-accent px-4 py-1.5 text-sm text-surface disabled:opacity-50"
        >
          {pending ? "Saving…" : "Save"}
        </button>
        {row.has_server_side && (
          <button
            type="button"
            onClick={sendTest}
            disabled={testing || !row.credential_configured || !row.pixel_id}
            className="rounded border border-line px-4 py-1.5 text-sm disabled:opacity-50"
            title="Sends a real, zero-value event so you can see it arrive in the platform's console."
          >
            {testing ? "Sending…" : "Send test event"}
          </button>
        )}
        {message && <span className="text-xs text-muted">{message}</span>}
      </div>

      {testResult && <TestOutcome result={testResult} />}
    </section>
  );
}

function TestOutcome({ result }: { result: TestEventResult }) {
  if (result.ok) {
    return (
      <p className="mt-3 rounded border border-line bg-surface p-2 text-xs">
        <span className="font-medium">Accepted.</span>{" "}
        {result.validated_only
          ? "Google validated the request in full and recorded nothing — it has no test console, so a landed test would be a real purchase."
          : result.used_test_event_code
            ? "Look for it in the platform's test-events console."
            : "No test code was set, so this landed in the LIVE dataset as a zero-value purchase."}
      </p>
    );
  }
  if (result.error === "missing_credential") {
    return (
      <p className="mt-3 text-xs text-warn">
        No credential on the server: {result.missing_settings?.join(", ")}.
      </p>
    );
  }
  return (
    <p className="mt-3 rounded border border-warn/30 bg-warn/5 p-2 text-xs text-warn">
      <span className="font-medium">Refused{result.status ? ` (${result.status})` : ""}.</span>{" "}
      {result.response || result.error || "The platform did not accept the event."}
    </p>
  );
}

function Toggle({
  label,
  checked,
  onChange,
  hint,
  disabled = false,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <label className={`flex items-start gap-2 ${disabled ? "opacity-50" : ""}`}>
      <input
        type="checkbox"
        checked={checked && !disabled}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-line"
      />
      <span>
        <span className="text-sm">{label}</span>
        {hint && <span className="mt-0.5 block max-w-[22rem] text-xs text-muted">{hint}</span>}
      </span>
    </label>
  );
}
