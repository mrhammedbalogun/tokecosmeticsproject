"use server";

/**
 * The two writes on the staff page: invite somebody, and revoke an invite.
 *
 * BOTH ARE SERVER FUNCTIONS, matching every other authenticated write in this app. They
 * get Next's Origin/Host check for free and they may persist a rotated token, which a
 * Server Component may not — so `fetchWithAuth` (the renewing fetcher) is the correct
 * one here, unlike on the pages.
 *
 * NEITHER REDIRECTS. Both return a state object and call `revalidatePath("/staff")`, so
 * the page re-renders with the new list in the same round trip. A redirect would work but
 * would throw away the success message, and "did the invite send?" is the one question
 * this page has to answer unambiguously.
 *
 * THE VALIDATION HERE IS NOT THE CONTROL. A Server Function is a public POST endpoint:
 * the dropdown constrains a browser, not a caller. Django validates the role against
 * `rbac.ROLES` and the whole call against `HasAdminScope("staff.manage")`. What the
 * checks below buy is that a mistyped or hand-crafted request does not become a row in
 * the audit log — the one log that should be all signal — and that the invite id cannot
 * be used to build a URL path nobody wrote.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { isRole } from "@/lib/staff";

export interface InviteState {
  error?: string;
  success?: string;
}

export interface RevokeState {
  error?: string;
}

const STAFF_PATH = "/staff";

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

/** The first message out of a DRF error body, or null. DRF answers either
 *  `{"detail": "…"}` or `{"field": ["…"]}`, and both are worth showing verbatim: the two
 *  refusals this endpoint makes ("already staff", "already invited") are explained there
 *  and nowhere else. */
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

export async function inviteAction(
  _prevState: InviteState,
  formData: FormData,
): Promise<InviteState> {
  const email = field(formData, "email").toLowerCase();
  const role = field(formData, "role");

  if (!email || !role) return { error: "Enter an address and a role." };
  if (!isRole(role)) return { error: `${role} is not a role.` };

  try {
    await fetchWithAuth("/admin/staff/invites/", {
      method: "POST",
      body: { email, role },
    });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) {
      return { error: "Only the Owner can invite staff." };
    }
    return { error: backendMessage(e.data) ?? "The invite could not be sent." };
  }

  revalidatePath(STAFF_PATH);
  return { success: `Invite sent to ${email}.` };
}

export async function revokeAction(
  _prevState: RevokeState,
  formData: FormData,
): Promise<RevokeState> {
  const id = field(formData, "invite_id");
  // Interpolated into a URL PATH, so the shape is checked before it gets there. `/^\d+$/`
  // and not `Number(id)`: the latter accepts "1e3", " 1 " and "0x2", each of which
  // addresses something other than what the operator clicked.
  if (!/^\d+$/.test(id) || Number(id) < 1) {
    return { error: "That invite could not be identified." };
  }

  try {
    await fetchWithAuth(`/admin/staff/invites/${id}/revoke/`, { method: "POST" });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 403) return { error: "Only the Owner can revoke invites." };
    if (e.status === 404) return { error: "That invite no longer exists." };
    return { error: backendMessage(e.data) ?? "The invite could not be revoked." };
  }

  revalidatePath(STAFF_PATH);
  return {};
}
