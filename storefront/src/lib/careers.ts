/**
 * The careers board's data layer (Plan-45) — the shapes `/api/v1/careers/…` serves, the
 * server-side readers the two pages render from, and the browser-side apply flow.
 *
 * ── WHY THE APPLY CALL GOES STRAIGHT TO DJANGO ──────────────────────────────────────
 *
 * Every other write in this app goes through a route handler in `app/api/`. This one
 * does not, and the reason is measured rather than stylistic:
 *
 *   1. The CV is uploaded BY THE BROWSER, to S3, using a ticket Django mints. A Vercel
 *      function caps a request body at 4.5MB and a Server Action at 1MB, both under the
 *      5MB a scanned CV reaches.
 *   2. Django's abuse throttles key on `CF-Connecting-IP`. A BFF hop replaces that with
 *      Vercel's egress address, so every applicant in the world would share one bucket —
 *      `backend/apps/accounts/throttling.py` measures exactly this and says not to.
 *
 * CSP already allows both hosts (`lib/csp.ts`: the API origin was always there, the S3
 * upload host was added for this), and production CORS already lists this origin. A
 * multipart POST with no custom headers and a JSON POST are both CORS-simple, so there
 * is no preflight in the path to break.
 *
 * ── THE PAGE IS PRERENDERED; ONLY THE FORM IS LIVE ──────────────────────────────────
 *
 * `getJobs` and `getJob` are revalidating fetches tagged `careers`, which Django flushes
 * on every posting write (`apps/careers/revalidate.py`). That is what keeps `/careers`
 * inside the `(static-shop)` route group — see its layout for the rules.
 */
import { apiFetch } from "@/lib/api";

/** Must match `apps/careers/revalidate.py::STOREFRONT_TAG`. */
export const CAREERS_TAG = "careers";

export interface JobLocation {
  id: number;
  label: string;
}

export interface Job {
  slug: string;
  title: string;
  department: string;
  employment_type: string;
  employment_type_label: string;
  workplace_type: string;
  workplace_type_label: string;
  country_name: string;
  country_code: string;
  compensation_text: string;
  summary: string;
  /** Sanitised HTML from the backend; rendered under `.rich-text`. */
  description: string;
  requirements: string;
  locations: JobLocation[];
  status: "open" | "closed";
  /** The SERVER's answer to "can somebody apply right now?" — it folds in the closing
   *  date, which a client clock has no business deciding. */
  is_accepting: boolean;
  published_at: string | null;
  closes_at: string | null;
}

/** Every role on the board. `null` means the API could not be reached — distinct from
 *  `[]`, which means we are genuinely not hiring. The page renders different words for
 *  each, because "we have no openings" is a claim and an outage is not. */
export async function getJobs(): Promise<Job[] | null> {
  try {
    return await apiFetch<Job[]>("/careers/jobs/", {
      next: { revalidate: 300, tags: [CAREERS_TAG] },
    });
  } catch {
    return null;
  }
}

export async function getJob(slug: string): Promise<Job | null> {
  try {
    return await apiFetch<Job>(`/careers/jobs/${encodeURIComponent(slug)}/`, {
      next: { revalidate: 300, tags: [CAREERS_TAG] },
    });
  } catch {
    return null;
  }
}

// ── the browser half ────────────────────────────────────────────────────────────────

/** Where the browser talks to Django directly. Published to the client deliberately —
 *  it is in the page source of every product page already (`lib/media.ts`). */
function apiOrigin(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

export const MAX_RESUME_BYTES = 5 * 1024 * 1024;

/** The extensions the backend's sniffer will accept. Checked here FIRST so a wrong file
 *  is caught before it is uploaded — the backend re-checks the real bytes regardless,
 *  and this list existing in two places is deliberate: one is courtesy, one is the rule. */
export const RESUME_EXTENSIONS = [".pdf", ".doc", ".docx"] as const;
export const RESUME_ACCEPT =
  ".pdf,.doc,.docx,application/pdf,application/msword," +
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export function resumeProblem(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!RESUME_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return "Attach your CV as a PDF, DOC or DOCX file.";
  }
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_RESUME_BYTES) return "That file is larger than 5MB.";
  return null;
}

interface UploadTicket {
  mode: "s3" | "direct";
  url: string;
  fields: Record<string, string>;
  key: string;
}

export class ApplyError extends Error {
  constructor(
    message: string,
    /** Keyed by form field, when the backend named one. */
    public fieldErrors: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApplyError";
  }
}

/** DRF answers in two shapes — `{field: ["msg"]}` and `{detail: "msg"}` — and both reach
 *  here. Anything unrecognised becomes one honest sentence rather than a JSON blob
 *  rendered at somebody applying for a job. */
function toApplyError(status: number, data: unknown, fallback: string): ApplyError {
  const body = (data ?? {}) as Record<string, unknown>;
  if (typeof body.detail === "string") return new ApplyError(body.detail);

  const fieldErrors: Record<string, string> = {};
  for (const [field, value] of Object.entries(body)) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[field] = first;
  }
  if (Object.keys(fieldErrors).length > 0) {
    return new ApplyError("Please check the highlighted fields.", fieldErrors);
  }
  if (status === 429) {
    return new ApplyError("That is a lot of attempts. Wait a minute and try again.");
  }
  return new ApplyError(fallback);
}

/**
 * Upload one CV and report progress. Two steps, both in the browser.
 *
 * XHR rather than `fetch`, for one reason: `fetch` has no upload-progress event, and a
 * 5MB file on a Nigerian mobile connection is thirty seconds of a form that otherwise
 * looks frozen. A progress bar is the difference between "it is working" and a second
 * click on Submit.
 */
export async function uploadResume(
  file: File,
  opts: { turnstileToken?: string; onProgress?: (percent: number) => void } = {},
): Promise<string> {
  const ticketResponse = await fetch(`${apiOrigin()}/api/v1/careers/uploads/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      size: file.size,
      turnstile_token: opts.turnstileToken ?? "",
    }),
  });
  if (!ticketResponse.ok) {
    throw toApplyError(
      ticketResponse.status,
      await ticketResponse.json().catch(() => null),
      "We could not start that upload. Try again.",
    );
  }
  const ticket = (await ticketResponse.json()) as UploadTicket;

  const form = new FormData();
  for (const [key, value] of Object.entries(ticket.fields)) form.append(key, value);
  // LAST, and it matters: S3's POST policy requires `file` to be the final field, and a
  // form that appends it earlier is refused with a signature error that says nothing
  // about ordering.
  form.append("file", file);

  const target =
    ticket.mode === "s3" ? ticket.url : `${apiOrigin()}${ticket.url}`;

  await new Promise<void>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", target);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && opts.onProgress) {
        opts.onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    request.onload = () =>
      request.status >= 200 && request.status < 300
        ? resolve()
        : reject(new ApplyError("Your CV could not be uploaded. Try again."));
    request.onerror = () =>
      reject(new ApplyError("Your CV could not be uploaded. Check your connection."));
    request.onabort = () => reject(new ApplyError("The upload was cancelled."));
    request.send(form);
  });

  return ticket.key;
}

export interface ApplicationDraft {
  full_name: string;
  email: string;
  phone: string;
  cover_letter: string;
  location: number | null;
  upload_key: string;
  resume_filename: string;
  /** The honeypot. Always sent, always empty for a human. */
  website: string;
  turnstile_token?: string;
}

export async function submitApplication(
  slug: string,
  draft: ApplicationDraft,
): Promise<void> {
  const response = await fetch(
    `${apiOrigin()}/api/v1/careers/jobs/${encodeURIComponent(slug)}/apply/`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    },
  );
  if (!response.ok) {
    throw toApplyError(
      response.status,
      await response.json().catch(() => null),
      "We could not send your application. Try again in a moment.",
    );
  }
}

// ── shared presentation helpers ─────────────────────────────────────────────────────

/** "Lagos", "Lagos and 10 other locations", "11 locations". What a card says under the
 *  title, so the board reads as five roles rather than fifteen near-identical rows. */
export function locationSummary(job: Job): string {
  const labels = job.locations.map((l) => l.label);
  if (labels.length === 0) return job.country_name;
  if (labels.length === 1) return labels[0];
  if (labels.length === 2) return `${labels[0]} and ${labels[1]}`;
  return `${labels[0]} and ${labels.length - 1} other locations`;
}

/** Every distinct location across the board, for the filter. Sorted by how many roles
 *  mention each, so the cities we are actually hiring in lead. */
export function allLocations(jobs: Job[]): string[] {
  const counts = new Map<string, number>();
  for (const job of jobs) {
    for (const location of job.locations) {
      counts.set(location.label, (counts.get(location.label) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([label]) => label);
}
