"use server";

/** Delivery-option writes (Plan-19b). `products.manage`.
 *
 * FLAT FIELDS ONLY — coverage is read-only until 19d, which owns the 811-region tree. */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface DeliveryState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
}

export async function saveDeliveryOptionAction(input: {
  id: number;
  name: string;
  price: string;
  free_over: string;
  min_days: string;
  max_days: string;
  disclaimer: string;
  is_active: boolean;
}): Promise<DeliveryState> {
  if (!input.name.trim()) return { fieldErrors: { name: "An option needs a name." } };
  const min = Number(input.min_days);
  const max = Number(input.max_days);
  if (!Number.isInteger(min) || !Number.isInteger(max) || min < 0 || max < 0) {
    return { fieldErrors: { min_days: "Delivery estimates are whole numbers of days." } };
  }
  if (min > max) {
    return {
      fieldErrors: { min_days: "The fastest estimate cannot be slower than the slowest." },
    };
  }

  try {
    await fetchWithAuth(`/admin/delivery-options/${input.id}/`, {
      method: "PATCH",
      body: {
        name: input.name.trim(),
        price: input.price || "0",
        free_over: input.free_over === "" ? null : input.free_over,
        min_days: min,
        max_days: max,
        disclaimer: input.disclaimer,
        is_active: input.is_active,
      },
    });
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    const data = e.data as Record<string, unknown> | undefined;
    const fieldErrors: Record<string, string> = {};
    for (const [key, value] of Object.entries(data ?? {})) {
      const first = Array.isArray(value) ? value[0] : value;
      if (typeof first === "string") fieldErrors[key] = first;
    }
    return Object.keys(fieldErrors).length
      ? { fieldErrors }
      : { message: "That option could not be saved." };
  }
  revalidatePath("/settings/delivery");
  return { savedAt: Date.now() };
}
