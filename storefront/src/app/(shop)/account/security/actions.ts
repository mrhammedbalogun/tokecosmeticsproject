"use server";

/**
 * Password change and account deletion. Server Functions (Origin-checked, JS-free).
 *
 * Deletion is the one action here that ends the session: the backend deactivates the
 * account and blacklists every outstanding refresh token, so the cookies this browser
 * holds are dead the moment the call returns — clearing them and redirecting home is
 * bookkeeping, not the security boundary.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { fetchWithAuth } from "@/lib/session";
import { clearTokens } from "@/lib/auth-session";
import { ApiError } from "@/lib/api";
import { accountErrorMessage } from "@/lib/auth-errors";

export interface PasswordChangeState {
  changed?: boolean;
  error?: string;
}

export interface DeleteAccountState {
  error?: string;
}

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

export async function changePasswordAction(
  _prevState: PasswordChangeState,
  formData: FormData,
): Promise<PasswordChangeState> {
  const oldPassword = field(formData, "old_password");
  const newPassword = field(formData, "new_password");
  const confirm = field(formData, "confirm");

  if (!oldPassword || !newPassword) {
    return { error: "Enter your current password and a new one." };
  }
  if (newPassword !== confirm) return { error: "The two new passwords don't match." };

  try {
    await fetchWithAuth("/auth/password/change/", {
      method: "POST",
      body: { old_password: oldPassword, new_password: newPassword },
    });
  } catch (e) {
    if (e instanceof ApiError) {
      return { error: accountErrorMessage(e.status, e.data, "We couldn't change your password — please try again.") };
    }
    return { error: "We couldn't change your password — please try again." };
  }

  return { changed: true };
}

export async function deleteAccountAction(
  _prevState: DeleteAccountState,
  formData: FormData,
): Promise<DeleteAccountState> {
  // Server-side too, not only in the UI: a Server Function is a public POST
  // endpoint, and this one destroys an account.
  if (field(formData, "confirm_phrase").trim() !== "DELETE") {
    return { error: 'Type DELETE (in capitals) to confirm.' };
  }

  const password = field(formData, "password");
  if (!password) return { error: "Enter your password to confirm." };

  try {
    await fetchWithAuth("/auth/account/delete/", {
      method: "POST", body: { password },
    });
  } catch (e) {
    if (e instanceof ApiError) {
      return { error: accountErrorMessage(e.status, e.data, "We couldn't delete your account — please try again.") };
    }
    return { error: "We couldn't delete your account — please try again." };
  }

  clearTokens(await cookies());
  // Outside the try — redirect() throws NEXT_REDIRECT and a catch above would eat it.
  redirect("/");
}
