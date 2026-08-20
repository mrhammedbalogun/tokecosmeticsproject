"use server";

/** Delivery-partner writes (Plan-39). Partner accounts (kill-switch, email, password)
 * are `settings.manage` — setting a password mints a credential for an external
 * business. Zone fixes are `products.manage`, same scope as delivery options. The
 * scopes are enforced by the backend; these actions just forward and translate. */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

const PATH = "/settings/partners";

export interface PartnerSaveState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
}

function stateFrom(e: unknown): PartnerSaveState {
  if (!(e instanceof ApiError)) return { message: "The API is not responding." };
  if (e.status === 403) return { message: "Your role does not include this change." };
  const data = e.data as Record<string, unknown> | undefined;
  const fieldErrors: Record<string, string> = {};
  for (const [key, value] of Object.entries(data ?? {})) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[key] = first;
  }
  return Object.keys(fieldErrors).length
    ? { fieldErrors }
    : { message: "That could not be saved." };
}

export async function savePartnerAction(input: {
  id: number;
  is_active?: boolean;
  email?: string;
}): Promise<PartnerSaveState> {
  const body: Record<string, unknown> = {};
  if (input.is_active !== undefined) body.is_active = input.is_active;
  if (input.email !== undefined) {
    if (!input.email.trim()) return { fieldErrors: { email: "An email is required." } };
    body.email = input.email.trim();
  }
  try {
    await fetchWithAuth(`/admin/partners/${input.id}/`, { method: "PATCH", body });
  } catch (e) {
    return stateFrom(e);
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}

export async function setPartnerPasswordAction(input: {
  id: number;
  password: string;
}): Promise<PartnerSaveState> {
  if (input.password.length < 12) {
    return {
      fieldErrors: { password: "Use at least 12 characters — this login has no second factor." },
    };
  }
  try {
    await fetchWithAuth(`/admin/partners/${input.id}/password/`, {
      method: "POST",
      body: { password: input.password },
    });
  } catch (e) {
    return stateFrom(e);
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}

export async function savePartnerZoneAction(input: {
  id: number;
  price: string; // "" = clear the price (hides the row at checkout)
  is_active: boolean;
}): Promise<PartnerSaveState> {
  try {
    await fetchWithAuth(`/admin/partner-zones/${input.id}/`, {
      method: "PATCH",
      body: {
        price: input.price.trim() === "" ? null : input.price.trim(),
        is_active: input.is_active,
      },
    });
  } catch (e) {
    return stateFrom(e);
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}

export async function deletePartnerZoneAction(input: { id: number }): Promise<PartnerSaveState> {
  try {
    await fetchWithAuth(`/admin/partner-zones/${input.id}/`, { method: "DELETE" });
  } catch (e) {
    return stateFrom(e);
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}
