"use client";

/**
 * Write or edit one role, locations and all, in one save.
 *
 * ── LOCATIONS ARE A LIST YOU EDIT IN PLACE, AND THE IDS MATTER ──────────────────────
 *
 * Each row keeps the id it arrived with, and the save sends it back. That is what lets
 * the backend UPDATE the row rather than delete-and-recreate it — and applications point
 * at these rows, so recreating them would null every applicant's chosen city on every
 * edit of the posting. Removing a row here really does remove it, which the backend
 * absorbs with SET_NULL and the application's own label snapshot.
 *
 * ── PASTE-A-LIST EXISTS BECAUSE OF THE ELEVEN SALES CITIES ──────────────────────────
 *
 * Typing eleven locations one field at a time is the thing that makes somebody give up
 * and post eleven separate roles instead — which is precisely the shape this model was
 * built to replace. One textarea, one city per line.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { RichTextField } from "@/components/RichTextField";
import { saveJob, type ActionState, type JobInput } from "@/app/(shell)/careers/actions";
import {
  EMPLOYMENT_TYPES,
  WORKPLACE_TYPES,
  type JobLocationRow,
  type JobRow,
} from "@/lib/careers";
import type { CountryRef } from "@/lib/reference";

const inputClass =
  "w-full rounded-[var(--radius-card)] border border-line bg-surface px-3 py-2 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-accent/30";

/** The datetime-local input wants `YYYY-MM-DDTHH:mm` in LOCAL time; the API speaks ISO
 *  UTC. Converting via the epoch minus the offset is the short spelling that survives
 *  a timezone that is not on the hour (Africa/Lagos is, but staff travel). */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function JobForm({
  job,
  countries,
  onDone,
}: {
  job: JobRow | null;
  countries: CountryRef[];
  onDone: () => void;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [state, setState] = useState<ActionState>({});

  const [form, setForm] = useState({
    title: job?.title ?? "",
    department: job?.department ?? "",
    employment_type: job?.employment_type ?? "full_time",
    workplace_type: job?.workplace_type ?? "on_site",
    country: job?.country ?? "NG",
    compensation_text: job?.compensation_text ?? "Good Pay",
    summary: job?.summary ?? "",
    // Typed `string`, not the narrow union `JobRow["status"]`: a <select> hands back a
    // plain string, and the alternative is a cast at the one place the value is set,
    // which would silence a real change of the option list later.
    status: (job?.status ?? "draft") as string,
    closes_at: toLocalInput(job?.closes_at ?? null),
    sort_order: job?.sort_order ?? 0,
  });
  const [description, setDescription] = useState(job?.description ?? "");
  const [requirements, setRequirements] = useState(job?.requirements ?? "");
  const [locations, setLocations] = useState<JobLocationRow[]>(
    job?.locations?.length ? job.locations.map((l) => ({ ...l })) : [],
  );
  const [bulk, setBulk] = useState("");

  function set<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function addBulk() {
    const added = bulk
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      // Case-insensitively new: the backend refuses two locations with the same name on
      // one posting, and discovering that from a 400 after pasting eleven lines is worse
      // than quietly not adding the duplicate.
      .filter(
        (label) =>
          !locations.some((row) => row.label.toLowerCase() === label.toLowerCase()),
      )
      .map((label) => ({ label }));
    if (added.length) setLocations((current) => [...current, ...added]);
    setBulk("");
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const input: JobInput = {
      slug: job?.slug ?? null,
      ...form,
      closes_at: form.closes_at ? new Date(form.closes_at).toISOString() : null,
      description,
      requirements,
      locations,
    };
    startTransition(async () => {
      const result = await saveJob(input);
      setState(result);
      if (result.savedAt) {
        router.refresh();
        onDone();
      }
    });
  }

  const errors = state.fieldErrors ?? {};

  return (
    <form onSubmit={submit} className="space-y-5">
      {state.message && (
        <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 px-4 py-3 text-sm text-warn">
          {state.message}
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Job title" error={errors.title}>
          <input
            className={inputClass}
            value={form.title}
            onChange={(e) => set("title", e.target.value)}
            required
            maxLength={140}
          />
        </Field>
        <Field
          label="Department"
          hint="Optional. Groups the card on the careers page — Sales, Operations…"
          error={errors.department}
        >
          <input
            className={inputClass}
            value={form.department}
            onChange={(e) => set("department", e.target.value)}
            maxLength={80}
          />
        </Field>
      </div>

      <Field
        label="One-line summary"
        hint="What the card says under the title. Keep it to a sentence."
        error={errors.summary}
      >
        <input
          className={inputClass}
          value={form.summary}
          onChange={(e) => set("summary", e.target.value)}
          maxLength={300}
        />
      </Field>

      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Employment type" error={errors.employment_type}>
          <select
            className={inputClass}
            value={form.employment_type}
            onChange={(e) => set("employment_type", e.target.value)}
          >
            {EMPLOYMENT_TYPES.map((type) => (
              <option key={type.value} value={type.value}>{type.label}</option>
            ))}
          </select>
        </Field>
        <Field label="Where the work happens" error={errors.workplace_type}>
          <select
            className={inputClass}
            value={form.workplace_type}
            onChange={(e) => set("workplace_type", e.target.value)}
          >
            {WORKPLACE_TYPES.map((type) => (
              <option key={type.value} value={type.value}>{type.label}</option>
            ))}
          </select>
        </Field>
        <Field label="Market" error={errors.country}>
          <select
            className={inputClass}
            value={form.country}
            onChange={(e) => set("country", e.target.value)}
          >
            {countries.map((country) => (
              <option key={country.code} value={country.code}>{country.name}</option>
            ))}
          </select>
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Pay" hint='Free text — "Good Pay", "₦250k–₦350k".' error={errors.compensation_text}>
          <input
            className={inputClass}
            value={form.compensation_text}
            onChange={(e) => set("compensation_text", e.target.value)}
            maxLength={120}
          />
        </Field>
        <Field
          label="Applications close"
          hint="Optional. The role stops taking applications on its own."
          error={errors.closes_at}
        >
          <input
            type="datetime-local"
            className={inputClass}
            value={form.closes_at}
            onChange={(e) => set("closes_at", e.target.value)}
          />
        </Field>
        <Field label="Order on the page" hint="Lower numbers come first." error={errors.sort_order}>
          <input
            type="number"
            min={0}
            className={inputClass}
            value={form.sort_order}
            onChange={(e) => set("sort_order", Number(e.target.value) || 0)}
          />
        </Field>
      </div>

      {/* --- locations ------------------------------------------------------ */}
      <div>
        <span className="block text-sm font-medium">Locations</span>
        <p className="mt-0.5 text-xs text-muted">
          One role, as many places as you are hiring in. The applicant picks one, and
          their choice is stored with the application. Leave empty for a single-site role.
        </p>
        {errors.locations && (
          <p className="mt-1 text-xs text-danger">{errors.locations}</p>
        )}

        <ul className="mt-3 space-y-2">
          {locations.map((row, index) => (
            <li key={row.id ?? `new-${index}`} className="flex gap-2">
              <input
                className={inputClass}
                value={row.label}
                maxLength={120}
                onChange={(e) =>
                  setLocations((current) =>
                    current.map((item, i) =>
                      i === index ? { ...item, label: e.target.value } : item,
                    ),
                  )
                }
              />
              <button
                type="button"
                onClick={() =>
                  setLocations((current) => current.filter((_, i) => i !== index))
                }
                className="shrink-0 rounded-[var(--radius-card)] border border-line px-3 text-sm text-muted hover:border-warn/40 hover:text-warn"
                aria-label={`Remove ${row.label || "this location"}`}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setLocations((current) => [...current, { label: "" }])}
            className="rounded-[var(--radius-card)] border border-line px-3 py-1.5 text-sm hover:border-accent/40"
          >
            Add a location
          </button>
        </div>

        <details className="mt-3">
          <summary className="cursor-pointer text-sm text-muted">
            Paste a list instead
          </summary>
          <textarea
            className={`${inputClass} mt-2`}
            rows={4}
            value={bulk}
            onChange={(e) => setBulk(e.target.value)}
            placeholder={"Alimosho, Lagos\nIba LG, Lagos\nAbuja"}
          />
          <button
            type="button"
            onClick={addBulk}
            className="mt-2 rounded-[var(--radius-card)] border border-line px-3 py-1.5 text-sm hover:border-accent/40"
          >
            Add these
          </button>
        </details>
      </div>

      <RichTextField
        label="The role"
        value={description}
        onChange={setDescription}
        error={errors.description}
        placeholder="What the person will actually do, day to day."
        rows={10}
      />
      <RichTextField
        label="What we are looking for"
        value={requirements}
        onChange={setRequirements}
        error={errors.requirements}
        placeholder="Experience, skills, where they need to be based."
        rows={8}
      />

      <Field
        label="Status"
        hint="Open puts it on tokecosmetics.com/careers. Closed keeps it listed but stops applications."
        error={errors.status}
      >
        <select
          className={inputClass}
          value={form.status}
          onChange={(e) => set("status", e.target.value)}
        >
          <option value="draft">Draft — not on the website</option>
          <option value="open">Open — accepting applications</option>
          <option value="closed">Closed — listed, not accepting</option>
        </select>
      </Field>

      <div className="flex flex-wrap gap-3 pt-2">
        <button
          type="submit"
          disabled={pending}
          className="rounded-[var(--radius-card)] bg-accent px-5 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {pending ? "Saving…" : job ? "Save changes" : "Create role"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="rounded-[var(--radius-card)] border border-line px-5 py-2 text-sm"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium">{label}</span>
      {hint && <span className="mt-0.5 block text-xs text-muted">{hint}</span>}
      <div className="mt-1.5">{children}</div>
      {error && <span className="mt-1 block text-xs text-danger">{error}</span>}
    </label>
  );
}
