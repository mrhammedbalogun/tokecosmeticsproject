"use server";

/**
 * The writes behind the Student Program → Notifications tab.
 *
 * DELIBERATELY NOT REUSED FROM `notifications/actions.ts`, even though the shapes match.
 * Those post to `/admin/notification-recipients/`, which is Owner-only and spans every
 * event; these post to `/admin/entrepreneurship/notifications/`, which is Owner +
 * Manager and reaches exactly one. Sharing the module would mean one `BASE` constant
 * deciding which permission boundary a click lands on, and the day somebody
 * parameterised it wrongly the mistake would be invisible on every screen using it.
 * One short file per screen, each with a fixed URL.
 *
 * `event` IS NOT SENT. The backend pins it (`ProgrammeRecipientSerializer` makes the
 * field read-only), so a value here would be decoration that looks load-bearing. The
 * shared
 * `NotificationSection` component still puts it in the form — it is written for the
 * general screen — and this file ignores it.
 *
 * THE VALIDATION HERE IS NOT THE CONTROL. A Server Function is a public POST endpoint;
 * Django re-checks the address, the staff id against `is_staff`, the scope, and the
 * event fence. What the checks below buy is that a mistyped request does not become a
 * row in the audit log.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

const PATH = "/entrepreneurship/notifications";
const BASE = "/admin/entrepreneurship/notifications/";

export interface AddState {
  error?: string;
  success?: string;
}

export interface RowState {
  error?: string;
  success?: string;
}

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

/** The first message out of a DRF error body, or null. Both shapes matter: the refusals
 *  this endpoint makes ("already on this list", "not an active staff member", "Only the
 *  Owner can confirm…") are explained there and nowhere else. */
function backendMessage(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const body = data as Record<string, unknown>;
  if (typeof body.detail === "string") return body.detail;
  for (const value of Object.values(body)) {
    if (typeof value === "string") return value;
    if (Array.isArray(value) && typeof value[0] === "string") return value[0];
  }
  return null;
}

/** `/^\d+$/` and not `Number(id)`: the latter accepts "1e3", " 1 " and "0x2", each of
 *  which addresses something other than what the operator clicked. */
function isId(value: string): boolean {
  return /^\d+$/.test(value) && Number(value) >= 1;
}

/** One sentence for a 403 on this surface. Not "only the Owner" — a Manager holds this
 *  screen, so the honest reason for a refusal here is a missing scope, not a rank. */
const DENIED =
  "Your role does not include changing who is emailed about programme applications.";

export async function addRecipientAction(
  _prevState: AddState,
  formData: FormData,
): Promise<AddState> {
  // "staff" | "external" — which half of the form was filled in. Sent explicitly rather
  // than inferred from which field is non-empty, so a browser that submits both (an
  // autofilled hidden input, a stale form) resolves to what the operator actually chose.
  const kind = field(formData, "kind");

  let body: Record<string, unknown>;
  let who: string;

  if (kind === "staff") {
    const userId = field(formData, "user");
    if (!isId(userId)) return { error: "Choose a staff member." };
    body = { user: Number(userId) };
    who = "That staff member";
  } else {
    const email = field(formData, "email").toLowerCase();
    // Deliberately loose. `type="email"` has already had a go and Django's EmailField is
    // the real check; a stricter regex here rejects valid addresses for no gain. What
    // this catches is an empty submit.
    if (!email || !email.includes("@")) return { error: "Enter an email address." };
    body = { email };
    who = email;
  }

  try {
    await fetchWithAuth(BASE, { method: "POST", body });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) return { error: DENIED };
    return { error: backendMessage(e.data) ?? "That recipient could not be added." };
  }

  revalidatePath(PATH);
  // Says PENDING for an external address rather than "will now be emailed", because it
  // will not be — not until somebody clicks the link. Claiming otherwise here is the
  // same silent-failure shape the confirmation gate exists to remove.
  return {
    success:
      kind === "staff"
        ? `${who} will now be emailed about new applications.`
        : `Confirmation sent to ${who}. They start receiving alerts once they click it.`,
  };
}

export async function removeRecipientAction(
  _prevState: RowState,
  formData: FormData,
): Promise<RowState> {
  const id = field(formData, "recipient_id");
  if (!isId(id)) return { error: "That recipient could not be identified." };

  try {
    await fetchWithAuth(`${BASE}${id}/`, { method: "DELETE" });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) return { error: DENIED };
    // Already gone is the state the operator wanted — including the case where the id
    // belongs to another event's row, which this endpoint answers 404 to on purpose.
    // Reporting an error would send somebody looking for a row that is not there.
    if (e.status === 404) {
      revalidatePath(PATH);
      return {};
    }
    return { error: backendMessage(e.data) ?? "That recipient could not be removed." };
  }

  revalidatePath(PATH);
  return {};
}

export async function resendConfirmationAction(
  _prevState: RowState,
  formData: FormData,
): Promise<RowState> {
  const id = field(formData, "recipient_id");
  if (!isId(id)) return { error: "That recipient could not be identified." };

  try {
    const result = await fetchWithAuth<{ sent_to: string }>(
      `${BASE}resend-confirmation/`,
      { method: "POST", body: { recipient_id: Number(id) } },
    );
    revalidatePath(PATH);
    return { success: `Confirmation link sent to ${result.sent_to}.` };
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) return { error: DENIED };
    // 429: the resend throttle. Its whole job is to cap outbound mail, so saying so is
    // more useful than a generic failure.
    if (e.status === 429) {
      return { error: "Too many confirmation emails just now. Try again in a minute." };
    }
    return { error: backendMessage(e.data) ?? "That link could not be sent." };
  }
}

export async function markConfirmedAction(
  _prevState: RowState,
  formData: FormData,
): Promise<RowState> {
  const id = field(formData, "recipient_id");
  if (!isId(id)) return { error: "That recipient could not be identified." };

  try {
    const result = await fetchWithAuth<{ confirmed: string }>(`${BASE}mark-confirmed/`, {
      method: "POST",
      body: { recipient_id: Number(id) },
    });
    revalidatePath(PATH);
    return { success: `${result.confirmed} is confirmed and will receive alerts.` };
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    // 403 HERE MEANS SOMETHING DIFFERENT from the other actions, so it gets its own
    // sentence. Vouching stays Owner-only even on this screen — confirming an address
    // reaches every pending subscription it has, including events this screen cannot
    // see. The backend explains that; pass its words through.
    if (e.status === 403) {
      return {
        error:
          backendMessage(e.data) ??
          "Only the Owner can confirm an address without its own click.",
      };
    }
    return { error: backendMessage(e.data) ?? "That address could not be confirmed." };
  }
}

export async function testSendAction(
  _prevState: RowState,
  formData: FormData,
): Promise<RowState> {
  const id = field(formData, "recipient_id");
  if (!isId(id)) return { error: "That recipient could not be identified." };

  try {
    const result = await fetchWithAuth<{ sent_to: string }>(`${BASE}test-send/`, {
      method: "POST",
      body: { recipient_id: Number(id) },
    });
    return { success: `Sample sent to ${result.sent_to}.` };
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) return { error: DENIED };
    return { error: backendMessage(e.data) ?? "That test could not be sent." };
  }
}
