/**
 * The Student Entrepreneurship Program admin's shapes, shared by its three screens.
 *
 * FOUR SCOPES, and the types keep the split visible: `ProgrammeSettings` is the intake
 * switch a `entrepreneurship.manage` holder edits; `ApplicationRow` is personal data
 * behind `entrepreneurship.applications.manage`, whose READS are audited. Nothing on the
 * settings shape carries a student.
 */

export type ApplicationStatus =
  | "new"
  | "in_review"
  | "approved"
  | "rejected"
  | "withdrawn";

export interface ApplicationRow {
  id: number;
  full_name: string;
  email: string;
  /** E.164 — what a `tel:`/WhatsApp link must be built from. Never rendered as-is. */
  phone: string;
  /** The readable form. Rendered; never linked. */
  phone_display: string;
  country_code: string;
  country_name: string;
  institution: string;
  academic_level: string;
  course_of_study: string;
  social_handle: string;
  has_motivation: boolean;
  status: ApplicationStatus;
  status_label: string;
  submission_count: number;
  is_resubmission: boolean;
  created_at: string;
}

export interface ApplicationDetail extends ApplicationRow {
  motivation: string;
  staff_notes: string;
  reviewed_at: string | null;
  reviewed_by_name: string;
}

export interface ProgrammeSettings {
  is_open: boolean;
  closed_message: string;
  updated_at: string;
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
  by_country: { country_id: string; country__name: string; count: number }[];
}

/** The five states, in the order a student moves through them. One list so the filter
 *  chips, the status buttons and the badge colours cannot disagree about the order.
 *
 *  `withdrawn` is last and is the only one that is not OUR decision — it records that
 *  the student stopped, which is the distinction a reviewer wants when the same person
 *  applies again next session. */
export const APPLICATION_STATUSES: { value: ApplicationStatus; label: string }[] = [
  { value: "new", label: "New" },
  { value: "in_review", label: "In review" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Not proceeding" },
  { value: "withdrawn", label: "Withdrew" },
];

export interface ApplicationFilters {
  status: string;
  country: string;
  q: string;
  page: number;
}

export function parseApplicationFilters(params: URLSearchParams): ApplicationFilters {
  return {
    status: params.get("status") ?? "",
    country: params.get("country") ?? "",
    q: (params.get("q") ?? "").trim(),
    page: Math.max(1, Number(params.get("page") ?? "1") || 1),
  };
}

export function applicationsQueryString(filters: ApplicationFilters): string {
  const query = new URLSearchParams();
  if (filters.status) query.set("status", filters.status);
  if (filters.country) query.set("country", filters.country);
  if (filters.q) query.set("q", filters.q);
  if (filters.page > 1) query.set("page", String(filters.page));
  return query.toString();
}

/** A WhatsApp link from a stored E.164 number — the channel this audience actually
 *  answers on, and the one a coordinator will reach for first. */
export function whatsappUrl(phoneE164: string): string {
  return `https://wa.me/${phoneE164.replace(/\D/g, "")}`;
}
