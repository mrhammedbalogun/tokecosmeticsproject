/**
 * The careers admin's shapes (Plan-45), shared by the two screens.
 *
 * TWO SCOPES, NOT ONE, and the types keep that visible: `JobRow` is content the
 * `careers.manage` holder edits; `ApplicationRow` is personal data behind
 * `careers.applications.manage`, whose READS are audited. Nothing on `JobRow` carries a
 * candidate, and nothing here carries a resume key — the API deliberately never serves
 * one, because a key that reaches a browser reaches its history and its screenshots.
 */

export interface JobLocationRow {
  id?: number;
  label: string;
  sort_order?: number;
}

export interface JobRow {
  id: number;
  title: string;
  slug: string;
  department: string;
  employment_type: string;
  employment_type_label: string;
  workplace_type: string;
  workplace_type_label: string;
  country: string;
  country_name: string;
  compensation_text: string;
  summary: string;
  description: string;
  requirements: string;
  status: "draft" | "open" | "closed";
  closes_at: string | null;
  sort_order: number;
  locations: JobLocationRow[];
  published_at: string | null;
  archived_at: string | null;
  is_accepting: boolean;
  is_archived: boolean;
  application_count: number;
  created_at: string;
  updated_at: string;
}

export type ApplicationStatus =
  | "new"
  | "in_review"
  | "shortlisted"
  | "rejected"
  | "hired";

export interface ApplicationRow {
  id: number;
  job: number;
  job_slug: string;
  job_title: string;
  location_label: string;
  full_name: string;
  email: string;
  /** E.164 — what a `tel:`/WhatsApp link must be built from. Never rendered as-is. */
  phone: string;
  /** The readable form. Rendered; never linked. */
  phone_display: string;
  status: ApplicationStatus;
  status_label: string;
  has_cover_letter: boolean;
  resume_original_name: string;
  resume_size: number;
  submission_count: number;
  is_resubmission: boolean;
  created_at: string;
}

export interface ApplicationDetail extends ApplicationRow {
  cover_letter: string;
  staff_notes: string;
  reviewed_at: string | null;
  reviewed_by_name: string;
  resume_content_type: string;
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface ApplicationStats {
  by_status: Partial<Record<ApplicationStatus, number>>;
  total: number;
  new: number;
  by_job: {
    id: number;
    title: string;
    slug: string;
    application_count: number;
    new_count: number;
  }[];
}

/** The five states, in the order a candidate moves through them. One list so the filter
 *  chips, the status select and the badge colours cannot disagree about the order. */
export const APPLICATION_STATUSES: { value: ApplicationStatus; label: string }[] = [
  { value: "new", label: "New" },
  { value: "in_review", label: "In review" },
  { value: "shortlisted", label: "Shortlisted" },
  { value: "rejected", label: "Not proceeding" },
  { value: "hired", label: "Hired" },
];

export const EMPLOYMENT_TYPES = [
  { value: "full_time", label: "Full-Time" },
  { value: "part_time", label: "Part-Time" },
  { value: "contract", label: "Contract" },
  { value: "internship", label: "Internship" },
  { value: "temporary", label: "Temporary" },
  { value: "volunteer", label: "Volunteer" },
];

export const WORKPLACE_TYPES = [
  { value: "on_site", label: "On-site" },
  { value: "hybrid", label: "Hybrid" },
  { value: "remote", label: "Remote" },
];

export interface JobFilters {
  status: string;
  q: string;
  page: number;
}

export function parseJobFilters(params: URLSearchParams): JobFilters {
  return {
    status: params.get("status") ?? "",
    q: (params.get("q") ?? "").trim(),
    page: Math.max(1, Number(params.get("page") ?? "1") || 1),
  };
}

export function jobsQueryString(filters: JobFilters): string {
  const query = new URLSearchParams();
  if (filters.status) query.set("status", filters.status);
  if (filters.q) query.set("q", filters.q);
  if (filters.page > 1) query.set("page", String(filters.page));
  return query.toString();
}

export interface ApplicationFilters {
  job: string;
  status: string;
  q: string;
  page: number;
}

export function parseApplicationFilters(params: URLSearchParams): ApplicationFilters {
  return {
    job: params.get("job") ?? "",
    status: params.get("status") ?? "",
    q: (params.get("q") ?? "").trim(),
    page: Math.max(1, Number(params.get("page") ?? "1") || 1),
  };
}

export function applicationsQueryString(filters: ApplicationFilters): string {
  const query = new URLSearchParams();
  if (filters.job) query.set("job", filters.job);
  if (filters.status) query.set("status", filters.status);
  if (filters.q) query.set("q", filters.q);
  if (filters.page > 1) query.set("page", String(filters.page));
  return query.toString();
}

/** "2.1 MB" / "480 KB". Rendered beside a CV's name so a reviewer can tell a one-page
 *  PDF from a scanned booklet before they open it. */
export function formatBytes(bytes: number): string {
  if (!bytes) return "";
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** A WhatsApp link from a stored E.164 number — the channel this customer base actually
 *  answers on, and the one a recruiter will reach for first. */
export function whatsappUrl(phoneE164: string): string {
  return `https://wa.me/${phoneE164.replace(/\D/g, "")}`;
}
