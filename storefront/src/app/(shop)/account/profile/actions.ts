"use server";

/**
 * Update the signed-in shopper's profile. A Server Function for the same reasons as
 * /login: Next's Origin/Host CSRF check comes free, and the form works without JS.
 *
 * Uses `fetchWithAuth` (not the RSC-safe fetchers): a Server Function may write
 * cookies, so the silent 401→refresh→retry path is allowed here and a stale access
 * token costs the user nothing.
 */
import { fetchWithAuth } from "@/lib/session";
import { ApiError } from "@/lib/api";
import { accountErrorMessage } from "@/lib/auth-errors";

export interface ProfileState {
  saved?: boolean;
  error?: string;
}

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export async function updateProfileAction(
  _prevState: ProfileState,
  formData: FormData,
): Promise<ProfileState> {
  const firstName = field(formData, "first_name");
  if (!firstName) return { error: "Enter your first name." };

  try {
    await fetchWithAuth("/auth/me/", {
      method: "PATCH",
      body: {
        first_name: firstName,
        // Empty strings are sent on purpose: clearing a field is a real edit.
        last_name: field(formData, "last_name"),
        phone: field(formData, "phone"),
        // An unticked checkbox is absent from FormData; send explicit false so the
        // stored value always reflects a real choice (same rule as registration).
        marketing_consent: formData.get("marketing_consent") !== null,
      },
    });
  } catch (e) {
    if (e instanceof ApiError) {
      return { error: accountErrorMessage(e.status, e.data, "We couldn't save your profile — please try again.") };
    }
    return { error: "We couldn't save your profile — please try again." };
  }

  return { saved: true };
}
