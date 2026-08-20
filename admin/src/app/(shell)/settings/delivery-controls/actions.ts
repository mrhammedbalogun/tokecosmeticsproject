"use server";

/** Plan-41 writes: block rules and fee masks. Both are `products.manage` on the
 * backend (the coverage/price doctrine); these actions just forward and translate
 * field errors, same shape as the partner actions. */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

const PATH = "/settings/delivery-controls";

export interface ControlSaveState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
}

function stateFrom(e: unknown): ControlSaveState {
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

export async function createBlockAction(input: {
  service_code: string;
  country_code: string;
  state_region: number | null;
  area_region: number | null;
}): Promise<ControlSaveState> {
  if (!input.service_code) {
    return { fieldErrors: { service_code: "Pick the delivery service to block." } };
  }
  try {
    await fetchWithAuth("/admin/delivery-blocks/", { method: "POST", body: input });
  } catch (e) {
    return stateFrom(e);
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}

export async function saveBlockAction(input: {
  id: number;
  is_active: boolean;
}): Promise<ControlSaveState> {
  try {
    await fetchWithAuth(`/admin/delivery-blocks/${input.id}/`, {
      method: "PATCH",
      body: { is_active: input.is_active },
    });
  } catch (e) {
    return stateFrom(e);
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}

export async function deleteBlockAction(input: { id: number }): Promise<ControlSaveState> {
  try {
    await fetchWithAuth(`/admin/delivery-blocks/${input.id}/`, { method: "DELETE" });
  } catch (e) {
    return stateFrom(e);
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}

export async function createMaskAction(input: {
  service_code: string;
  percent: string;
}): Promise<ControlSaveState> {
  if (!input.service_code) {
    return { fieldErrors: { service_code: "Pick the delivery service to mask." } };
  }
  if (!input.percent.trim()) {
    return { fieldErrors: { percent: "Enter the percentage to add." } };
  }
  try {
    await fetchWithAuth("/admin/delivery-fee-masks/", {
      method: "POST",
      body: { service_code: input.service_code, percent: input.percent.trim() },
    });
  } catch (e) {
    return stateFrom(e);
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}

export async function saveMaskAction(input: {
  id: number;
  percent?: string;
  is_active?: boolean;
}): Promise<ControlSaveState> {
  const body: Record<string, unknown> = {};
  if (input.percent !== undefined) {
    if (!input.percent.trim()) {
      return { fieldErrors: { percent: "Enter the percentage to add." } };
    }
    body.percent = input.percent.trim();
  }
  if (input.is_active !== undefined) body.is_active = input.is_active;
  try {
    await fetchWithAuth(`/admin/delivery-fee-masks/${input.id}/`, {
      method: "PATCH",
      body,
    });
  } catch (e) {
    return stateFrom(e);
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}

export async function deleteMaskAction(input: { id: number }): Promise<ControlSaveState> {
  try {
    await fetchWithAuth(`/admin/delivery-fee-masks/${input.id}/`, { method: "DELETE" });
  } catch (e) {
    return stateFrom(e);
  }
  revalidatePath(PATH);
  return { savedAt: Date.now() };
}
