"use client";

/**
 * The stock CSV import wizard: upload → map columns → dry-run report → apply.
 * Plan-17c Task 6.
 *
 * ── THE PREVIEW AND THE APPLY SEND THE SAME BYTES ───────────────────────────────────
 *
 * The file is normalised ONCE, when the mapping is confirmed, and held. The dry-run posts
 * those bytes; the apply posts the identical string. Ruling 2 guarantees the backend runs
 * the same code both times — this guarantees it runs it over the same input, which is the
 * other half of "the preview cannot disagree with the apply". Re-deriving the CSV at apply
 * time would quietly reopen that gap.
 *
 * ── WHY THIS FETCHES THE BFF DIRECTLY ───────────────────────────────────────────────
 *
 * Every other write in this app is a Server Function, and this one is not: a file is
 * already in the browser and must be sent twice, unchanged. Handing the bytes to a Server
 * Function only to have it forward them adds a copy and a serialisation step between the
 * preview and the apply — the two things that must be identical. `/api/admin/...` is the
 * generic proxy the whole admin fetches through; it attaches the admin token server-side,
 * and it learned to carry multipart in Plan-17c Task 2 (before that, it silently discarded
 * every upload).
 *
 * NOTHING IS WRITTEN UNTIL "Apply". The wizard cannot reach the apply step without having
 * shown a dry-run report of the same file first.
 */
import { useState } from "react";
import { parseCsv } from "@/lib/csv";
import {
  buildImportCsv,
  guessColumns,
  IMPORT_FIELDS,
  missingRequired,
  type ColumnMap,
  type ImportReport,
} from "@/lib/stock-import";

type Step = "upload" | "map" | "preview" | "done";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function StockImportWizard() {
  const [step, setStep] = useState<Step>("upload");
  const [fileName, setFileName] = useState("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [rows, setRows] = useState<string[][]>([]);
  const [map, setMap] = useState<ColumnMap>({
    sku: "", warehouse: "", quantity: "", low_stock_threshold: "",
  });
  /** The normalised file. Built once at the end of the mapping step. */
  const [payload, setPayload] = useState("");
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setStep("upload");
    setFileName("");
    setHeaders([]);
    setRows([]);
    setPayload("");
    setReport(null);
    setError(null);
  };

  const onFile = async (file: File) => {
    setError(null);
    const text = await file.text();
    const parsed = parseCsv(text);
    if (!parsed.headers.length || !parsed.rows.length) {
      setError("That file has no rows to import.");
      return;
    }
    setFileName(file.name);
    setHeaders(parsed.headers);
    setRows(parsed.rows);
    setMap(guessColumns(parsed.headers));
    setStep("map");
  };

  const send = async (bytes: string, dryRun: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", new Blob([bytes], { type: "text/csv" }), "stock.csv");
      const response = await fetch(
        `/api/admin/stock/import.csv${dryRun ? "?dry_run=1" : ""}`,
        { method: "POST", body: form },
      );
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        setError(
          (data as { detail?: string } | null)?.detail ??
            "The import could not be processed.",
        );
        return null;
      }
      return data as ImportReport;
    } catch {
      setError("The API is not responding.");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const runDryRun = async () => {
    const bytes = buildImportCsv(headers, rows, map);
    const result = await send(bytes, true);
    if (result) {
      setPayload(bytes); // held, so the apply sends exactly what was previewed
      setReport(result);
      setStep("preview");
    }
  };

  const apply = async () => {
    const result = await send(payload, false);
    if (result) {
      setReport(result);
      setStep("done");
    }
  };

  const missing = missingRequired(map);

  return (
    <div className="space-y-4">
      <Steps current={step} />

      {error && (
        <p className="rounded border border-warn/30 bg-warn/5 p-3 text-sm text-warn" role="alert">
          {error}
        </p>
      )}

      {step === "upload" && (
        <div className="rounded-[var(--radius-card)] border border-line p-4">
          <label className="block text-sm">
            Choose a CSV
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void onFile(file);
              }}
              className="mt-2 block w-full text-sm"
            />
          </label>
          <p className="mt-3 text-sm text-muted">
            It needs a SKU, a warehouse name and a quantity. The column names do not
            matter — you map them on the next step. Quantities are absolute counts, not
            changes.
          </p>
          <p className="mt-2 text-sm text-muted">
            The export on the inventory page is already in the right shape, if you want a
            starting point.
          </p>
        </div>
      )}

      {step === "map" && (
        <div className="rounded-[var(--radius-card)] border border-line p-4">
          <p className="text-sm">
            <strong>{fileName}</strong> — {rows.length} {rows.length === 1 ? "row" : "rows"}.
            Check the columns.
          </p>

          <div className="mt-4 space-y-3">
            {IMPORT_FIELDS.map((field) => (
              <label key={field.key} className="block text-xs text-muted">
                {field.label}
                {!field.required && " (optional)"}
                <select
                  value={map[field.key]}
                  onChange={(e) => setMap((m) => ({ ...m, [field.key]: e.target.value }))}
                  className={`mt-1 ${FIELD}`}
                >
                  <option value="">— not in this file —</option>
                  {headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>

          {missing.length > 0 && (
            <p className="mt-3 text-sm text-warn">
              Still needed: {missing.join(", ")}.
            </p>
          )}

          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => void runDryRun()}
              disabled={busy || missing.length > 0}
              className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
            >
              {busy ? "Checking…" : "Check this file"}
            </button>
            <button
              type="button"
              onClick={reset}
              className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
            >
              Start over
            </button>
          </div>
          <p className="mt-2 text-xs text-muted">Checking writes nothing.</p>
        </div>
      )}

      {step === "preview" && report && (
        <div className="rounded-[var(--radius-card)] border border-line p-4">
          <h2 className="text-sm font-semibold">Nothing has been saved yet</h2>
          <ReportSummary report={report} verb="would be" />
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => void apply()}
              disabled={busy || report.created + report.updated === 0}
              className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
            >
              {busy ? "Applying…" : `Apply ${report.created + report.updated} rows`}
            </button>
            <button
              type="button"
              onClick={() => setStep("map")}
              className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
            >
              Back to columns
            </button>
          </div>
          {report.errors.length > 0 && (
            <p className="mt-2 text-xs text-muted">
              Rows with errors are skipped; the rest still apply.
            </p>
          )}
        </div>
      )}

      {step === "done" && report && (
        <div className="rounded-[var(--radius-card)] border border-ok/40 bg-ok/5 p-4">
          <h2 className="text-sm font-semibold text-ok">Imported</h2>
          <ReportSummary report={report} verb="were" />
          <button
            type="button"
            onClick={reset}
            className="mt-4 rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
          >
            Import another file
          </button>
        </div>
      )}
    </div>
  );
}

function Steps({ current }: { current: Step }) {
  const steps: { key: Step; label: string }[] = [
    { key: "upload", label: "1. Choose a file" },
    { key: "map", label: "2. Map columns" },
    { key: "preview", label: "3. Check" },
    { key: "done", label: "4. Apply" },
  ];
  return (
    <ol className="flex flex-wrap gap-2 text-xs">
      {steps.map((step) => (
        <li
          key={step.key}
          aria-current={step.key === current ? "step" : undefined}
          className={`rounded border px-2 py-1 ${
            step.key === current
              ? "border-accent text-accent"
              : "border-line text-muted"
          }`}
        >
          {step.label}
        </li>
      ))}
    </ol>
  );
}

function ReportSummary({ report, verb }: { report: ImportReport; verb: string }) {
  return (
    <div className="mt-2 text-sm">
      <p>
        <strong>{report.created}</strong> {verb} created, <strong>{report.updated}</strong>{" "}
        {verb} updated
        {report.errors.length > 0 && (
          <>
            , <strong className="text-warn">{report.errors.length}</strong> skipped
          </>
        )}
        .
      </p>
      {report.errors.length > 0 && (
        <ul className="mt-3 max-h-64 space-y-1 overflow-y-auto rounded border border-line p-2 text-xs">
          {report.errors.map((row) => (
            <li key={row.row} className="text-warn">
              {/* +1 for the header, so this is the line number in their spreadsheet. */}
              Line {row.row + 1}: {row.error}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
