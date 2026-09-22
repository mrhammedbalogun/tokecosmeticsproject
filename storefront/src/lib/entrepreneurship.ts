/**
 * The Student Entrepreneurship Program's data layer — the two shapes
 * `/api/v1/entrepreneurship/…` serves, the server-side reader the page renders from,
 * and the browser-side submit.
 *
 * ── WHY THE APPLY CALL GOES STRAIGHT TO DJANGO ──────────────────────────────────────
 *
 * Same reason the careers form does, minus the file. Django's abuse throttles key on
 * `CF-Connecting-IP`; a Next BFF hop replaces that with Vercel's egress address, so
 * every applicant in the world would share one bucket — and this form's ONLY rate
 * limit is that throttle, because there is no upload step in front of it to absorb a
 * script. `backend/apps/accounts/throttling.py` measures exactly this and says not to.
 *
 * A JSON POST with no custom headers is CORS-simple, so there is no preflight in the
 * path to break, and production CORS already lists this origin
 * (`CORS_ALLOWED_ORIGINS`). Turnstile's script host is already global in
 * `lib/csp.ts:40`, so this page needs no CSP change either.
 *
 * ── THE PAGE IS PRERENDERED; ONLY THE FORM IS LIVE ──────────────────────────────────
 *
 * `getProgrammeConfig` is a revalidating fetch tagged `entrepreneurship`, which Django
 * flushes whenever the intake switch is saved (`apps/entrepreneurship/revalidate.py`).
 * That is what keeps `/entrepreneurial-program` inside the `(static-shop)` route group.
 *
 * THIS IS A CONSTRAINT, NOT A PREFERENCE. That layout forbids anything that varies per
 * visitor — no cookies, no `headers()` — so "is the programme open?" may NOT become a
 * dynamic read. Simplifying this to one would silently drop the whole page out of
 * static rendering, which is how the currency popup came to be excluded from that
 * layout in the first place. The backend re-checks the same switch under a lock on
 * every submit, so a stale cache costs a refused submission with a clear message, never
 * a wrong acceptance.
 */
import { apiFetch } from "@/lib/api";

/** Must match `apps/entrepreneurship/revalidate.py::STOREFRONT_TAG`. */
export const PROGRAMME_TAG = "entrepreneurship";

export interface ProgrammeCountry {
  code: string;
  name: string;
}

export interface ProgrammeConfig {
  is_open: boolean;
  /** What to show in the form's place. Always present, even while open. */
  closed_message: string;
  countries: ProgrammeCountry[];
}

/**
 * The fallback when the API cannot be reached.
 *
 * OPEN, DELIBERATELY, and it is the one judgement call in this file. The alternative —
 * fail closed — would turn any backend blip into "this programme is not accepting
 * applications", which is a lie told to a real student who then leaves. Failing OPEN
 * shows the form; the submit then either works or is refused by the server with a real
 * reason. The server is the authority on both counts, so the worst case here is a
 * wasted form fill, and the worst case the other way is a lost applicant.
 *
 * The country list falls back to the four markets the shop sells into, so the dropdown
 * is never empty. If a market is ever added, this list going stale costs one missing
 * option until the API answers again — it does not break the form, because the server
 * validates the code it is sent regardless.
 */
const FALLBACK: ProgrammeConfig = {
  is_open: true,
  closed_message:
    "We have closed applications for this intake while we work through the ones we " +
    "have. Check back soon — the next intake opens here first.",
  countries: [
    { code: "NG", name: "Nigeria" },
    { code: "GB", name: "United Kingdom" },
    { code: "US", name: "United States" },
    { code: "CA", name: "Canada" },
  ],
};

export async function getProgrammeConfig(): Promise<ProgrammeConfig> {
  try {
    const config = await apiFetch<ProgrammeConfig>("/entrepreneurship/config/", {
      next: { revalidate: 300, tags: [PROGRAMME_TAG] },
    });
    // A malformed or half-deployed response must not blank the dropdown. Each field is
    // taken only when it is the shape the page needs.
    return {
      is_open: typeof config?.is_open === "boolean" ? config.is_open : FALLBACK.is_open,
      closed_message: config?.closed_message || FALLBACK.closed_message,
      countries:
        Array.isArray(config?.countries) && config.countries.length > 0
          ? config.countries
          : FALLBACK.countries,
    };
  } catch {
    return FALLBACK;
  }
}

// ── the browser half ────────────────────────────────────────────────────────────────

/** Where the browser talks to Django directly. Published to the client deliberately —
 *  it is in the page source of every product page already (`lib/media.ts`). */
function apiOrigin(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

export const MOTIVATION_MAX = 2000;

/** Suggestions, NOT a gate. The `<datalist>` behind the academic-level field: these are
 *  the answers most applicants will want, offered so a phone keyboard is optional — and
 *  the field stays free text, because "Year 2" and "Sophomore" are real answers from the
 *  other three markets this programme runs in. */
export const ACADEMIC_LEVELS = [
  "100 Level",
  "200 Level",
  "300 Level",
  "400 Level",
  "500 Level",
  "ND 1",
  "ND 2",
  "HND 1",
  "HND 2",
  "Postgraduate",
] as const;

export interface ApplicationDraft {
  country: string;
  full_name: string;
  email: string;
  phone: string;
  institution: string;
  academic_level: string;
  course_of_study: string;
  social_handle: string;
  motivation: string;
  /** The honeypot. Always sent, always empty for a human. */
  website: string;
  turnstile_token?: string;
}

export class ApplyError extends Error {
  constructor(
    message: string,
    /** Keyed by form field, when the backend named one. */
    public fieldErrors: Record<string, string> = {},
    /** 409 — the intake closed between the page rendering and the submit. The form
     *  renders this as the page's closed state rather than as a form error, because it
     *  is not something the applicant can fix by editing a field. */
    public intakeClosed = false,
  ) {
    super(message);
    this.name = "ApplyError";
  }
}

/** DRF answers in two shapes — `{field: ["msg"]}` and `{detail: "msg"}` — and both reach
 *  here. Anything unrecognised becomes one honest sentence rather than a JSON blob
 *  rendered at a student. */
function toApplyError(status: number, data: unknown, fallback: string): ApplyError {
  const body = (data ?? {}) as Record<string, unknown>;

  if (typeof body.detail === "string") {
    return new ApplyError(body.detail, {}, status === 409);
  }

  const fieldErrors: Record<string, string> = {};
  for (const [field, value] of Object.entries(body)) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[field] = first;
  }
  if (Object.keys(fieldErrors).length > 0) {
    return new ApplyError("Please check the highlighted fields.", fieldErrors);
  }
  if (status === 429) {
    return new ApplyError(
      "That is a lot of attempts from this connection. Wait a minute and try again.",
    );
  }
  if (status === 403) {
    // Turnstile refused, which on a shared campus connection is a real and recoverable
    // thing rather than an accusation.
    return new ApplyError(
      "We could not verify that you are a person. Refresh the page and try once more.",
    );
  }
  return new ApplyError(fallback);
}

export async function submitApplication(draft: ApplicationDraft): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${apiOrigin()}/api/v1/entrepreneurship/apply/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    });
  } catch {
    // A thrown `fetch` is the network, not the server — worth its own sentence, because
    // "check your connection" is actionable and "something went wrong" is not.
    throw new ApplyError(
      "We could not reach us just then. Check your connection and try again.",
    );
  }
  if (!response.ok) {
    throw toApplyError(
      response.status,
      await response.json().catch(() => null),
      "We could not send your application. Try again in a moment.",
    );
  }
}
