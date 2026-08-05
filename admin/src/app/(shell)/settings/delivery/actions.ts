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

/** The wizard's create: the option AND its coverage in one POST, so there is no
 * window where a coverage-less option sits active and matches nobody. The backend
 * serializer is the real boundary (unknown carriers, cross-currency coverage,
 * quote-without-disclaimer all 400 there); this action only pre-checks what makes a
 * friendlier inline message. */
export async function createDeliveryOptionAction(input: {
  name: string;
  price: string;
  free_over: string;
  min_days: string;
  max_days: string;
  disclaimer: string;
  quote_required: boolean;
  currency: string;
  country_codes: string[];
  region_ids: number[];
}): Promise<DeliveryState> {
  if (!input.name.trim()) return { fieldErrors: { name: "An option needs a name." } };
  if (!input.country_codes.length && !input.region_ids.length) {
    return { fieldErrors: { country_codes: "Choose where this option is offered." } };
  }
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
    await fetchWithAuth("/admin/delivery-options/", {
      method: "POST",
      body: {
        name: input.name.trim(),
        price: input.price || "0",
        free_over: input.free_over === "" ? null : input.free_over,
        min_days: min,
        max_days: max,
        disclaimer: input.disclaimer,
        quote_required: input.quote_required,
        currency: input.currency,
        country_codes: input.country_codes,
        region_ids: input.region_ids,
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
      : { message: "That option could not be created." };
  }
  revalidatePath("/settings/delivery");
  return { savedAt: Date.now() };
}

export interface DeliveryPreviewOption {
  id: number;
  name: string;
  kind: "manual" | "carrier";
  price: string | null;
  currency: string;
  quote_required: boolean;
  disclaimer: string;
  min_days: number;
  max_days: number;
}

/** The global address tester asks the BACKEND matcher — the one that decides at
 * checkout — rather than a client-side mirror that can only ever drift. */
export async function previewDeliveryAction(input: {
  country: string;
  state_region?: number;
  area_region?: number;
}): Promise<{ options?: DeliveryPreviewOption[]; resolvedCountry?: string; message?: string }> {
  const params = new URLSearchParams({ country: input.country });
  if (input.state_region) params.set("state_region", String(input.state_region));
  if (input.area_region) params.set("area_region", String(input.area_region));
  try {
    const data = await fetchWithAuth<{ country: string; options: DeliveryPreviewOption[] }>(
      `/admin/delivery-options/preview/?${params.toString()}`,
    );
    return { options: data.options, resolvedCountry: data.country };
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    return { message: "The preview could not be loaded." };
  }
}

/** Coverage is a REPLACE through its own endpoint (Plan-19d).
 *
 * Kept off the price PATCH deliberately: coverage is mixed granularity, and folding it in
 * would let a client that omitted the key silently clear every region — the exact class
 * of accident that makes "why did Lagos stop being served?" unanswerable. */
export async function saveCoverageAction(input: {
  id: number;
  country_codes: string[];
  region_ids: number[];
}): Promise<DeliveryState> {
  try {
    await fetchWithAuth(`/admin/delivery-options/${input.id}/coverage/`, {
      method: "PUT",
      body: { country_codes: input.country_codes, region_ids: input.region_ids },
    });
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    return { message: "That coverage could not be saved." };
  }
  revalidatePath("/settings/delivery");
  revalidatePath(`/settings/delivery/${input.id}`);
  return { savedAt: Date.now() };
}
