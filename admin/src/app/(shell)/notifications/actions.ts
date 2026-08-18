"use server";

/**
 * The writes on the Email Notifications page: add a recipient, remove one, send a test,
 * resend a confirmation link, or mark an address confirmed on the Owner's word.
 *
 * ALL OF THEM ARE SERVER FUNCTIONS, matching every other authenticated write in this app.
 * They get Next's Origin/Host check for free and may persist a rotated token, which a
 * Server Component may not — so `fetchWithAuth` (the renewing fetcher) is correct here,
 * unlike on the page itself.
 *
 * THE VALIDATION HERE IS NOT THE CONTROL, same as `staff/actions.ts`. A Server Function
 * is a public POST endpoint; the dropdown constrains a browser, not a caller. Django
 * validates the event against the registry, the staff id against `is_staff`, and the
 * whole call against `HasAdminScope("settings.manage")`. What the checks below buy is
 * that a mistyped or hand-crafted request does not become a row in the audit log.
 *
 * NONE REDIRECT. Each returns a state object and revalidates the page, so the list
 * re-renders in the same round trip with the message still on screen — and "did the test
 * email actually go?" is the one question this page has to answer unambiguously.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

const PATH = "/notifications";
const BASE = "/admin/notification-recipients/";

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

/** The first message out of a DRF error body, or null. DRF answers either
 *  `{"detail": "…"}` or `{"field": ["…"]}`; both matter here, because the refusals this
 *  endpoint makes ("already on this list", "not an active staff member") are explained
 *  there and nowhere else. */
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
 *  which addresses something other than what the operator clicked. Same rule as
 *  `staff/actions.ts` uses on invite ids. */
function isId(value: string): boolean {
  return /^\d+$/.test(value) && Number(value) >= 1;
}

export async function addRecipientAction(
  _prevState: AddState,
  formData: FormData,
): Promise<AddState> {
  const event = field(formData, "event");
  // "staff" | "external" — which half of the form was filled in. Sent explicitly rather
  // than inferred from which field is non-empty, so a browser that submits both (an
  // autofilled hidden input, a stale form) resolves to what the operator actually chose
  // instead of to whichever check runs first.
  const kind = field(formData, "kind");

  if (!event) return { error: "Choose a notification first." };

  let body: Record<string, unknown>;
  let who: string;

  if (kind === "staff") {
    const userId = field(formData, "user");
    if (!isId(userId)) return { error: "Choose a staff member." };
    body = { event, user: Number(userId) };
    who = "That staff member";
  } else {
    const email = field(formData, "email").toLowerCase();
    // Deliberately loose. The browser's `type="email"` has already had a go, Django's
    // EmailField is the real check, and a regex here that is stricter than either
    // rejects valid addresses for no gain. What this catches is an empty submit.
    if (!email || !email.includes("@")) return { error: "Enter an email address." };
    body = { event, email };
    who = email;
  }

  try {
    await fetchWithAuth(BASE, { method: "POST", body });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) return { error: "Only the Owner can change who gets emailed." };
    return { error: backendMessage(e.data) ?? "That recipient could not be added." };
  }

  revalidatePath(PATH);
  return { success: `${who} will now be emailed.` };
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
    if (e.status === 403) return { error: "Only the Owner can change who gets emailed." };
    // Already gone is the state the operator wanted. Reporting an error for it would
    // send somebody looking for a row that is not there.
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

  let sentTo = "";
  try {
    const result = await fetchWithAuth<{ sent_to?: string }>(`${BASE}resend-confirmation/`, {
      method: "POST",
      body: { recipient_id: Number(id) },
    });
    sentTo = result?.sent_to ?? "";
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) return { error: "Only the Owner can do that." };
    // The endpoint is rate-limited (10/hour) because it mails branded, official-looking
    // post to any address on demand. Say so rather than showing a bare failure.
    if (e.status === 429) {
      return { error: "Too many confirmation emails sent recently. Try again later." };
    }
    return { error: backendMessage(e.data) ?? "The confirmation could not be sent." };
  }

  // No `revalidatePath`: the row has not changed — it is still pending until they click —
  // and re-rendering would discard the confirmation the operator is waiting to read.
  return {
    success: sentTo
      ? `Confirmation re-sent to ${sentTo}.`
      : "Confirmation re-sent.",
  };
}

export async function markConfirmedAction(
  _prevState: RowState,
  formData: FormData,
): Promise<RowState> {
  const id = field(formData, "recipient_id");
  if (!isId(id)) return { error: "That recipient could not be identified." };

  try {
    await fetchWithAuth(`${BASE}mark-confirmed/`, {
      method: "POST",
      body: { recipient_id: Number(id) },
    });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) return { error: "Only the Owner can do that." };
    return { error: backendMessage(e.data) ?? "The address could not be confirmed." };
  }

  // DOES revalidate, unlike resend: the row's state has genuinely changed, and the
  // "Awaiting confirmation" badge disappearing is the feedback. A success message would
  // be lost anyway — the pending-row controls unmount when the badge does.
  revalidatePath(PATH);
  return {};
}

export async function testSendAction(
  _prevState: RowState,
  formData: FormData,
): Promise<RowState> {
  const id = field(formData, "recipient_id");
  if (!isId(id)) return { error: "That recipient could not be identified." };

  // NOTE the address is not in this body and must never be. The backend looks it up from
  // the stored row — an endpoint that mails an address supplied by the caller is an open
  // relay wearing a staff login. See the view's docstring.
  let sentTo = "";
  try {
    const result = await fetchWithAuth<{ sent_to?: string }>(`${BASE}test-send/`, {
      method: "POST",
      body: { recipient_id: Number(id) },
    });
    sentTo = result?.sent_to ?? "";
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) return { error: "Only the Owner can send test emails." };
    return { error: backendMessage(e.data) ?? "The test email could not be sent." };
  }

  // No `revalidatePath`: nothing about the list changed, and re-rendering it would
  // discard the one thing the operator is waiting to read.
  return {
    success: sentTo
      ? `Test email sent to ${sentTo}. It may take a minute to arrive.`
      : "Test email sent.",
  };
}
