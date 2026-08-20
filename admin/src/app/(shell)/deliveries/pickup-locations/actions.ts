"use server";

/**
 * Pickup-location writes (Plan-34, relocated here by Plan-35 — one home, or the two
 * drift). `products.manage`; the backend serializer is the boundary (E.164 phone,
 * Nigeria bounding box), these only pre-check what makes a friendlier inline message.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

const PAGE = "/deliveries/pickup-locations";

export interface SenderState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
}

export interface SenderLocationRow {
  id: number;
  name: string;
  phone: string;
  address: string;
  locality: string;
  latitude: string;
  longitude: string;
  /** Display-only filing labels (Plan-35) — GIG routing follows the pin, never these. */
  state: string;
  lga: string;
  /** Plan-40: offer this location to customers as a ₦0 pickup store… */
  customer_pickup: boolean;
  /** …matched to customers BY THIS canonical state (core.Region pk, level="state"). */
  state_region: number | null;
  is_active: boolean;
}

function senderFieldErrors(e: unknown): SenderState {
  if (!(e instanceof ApiError)) return { message: "The API is not responding." };
  const data = e.data as Record<string, unknown> | undefined;
  const fieldErrors: Record<string, string> = {};
  for (const [key, value] of Object.entries(data ?? {})) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[key] = first;
  }
  return Object.keys(fieldErrors).length
    ? { fieldErrors }
    : { message: "That pickup location could not be saved." };
}

/** Create + update share one action, same shape as the delivery-option saves. */
export async function saveSenderLocationAction(input: {
  id: number | null;
  name: string;
  phone: string;
  address: string;
  locality: string;
  latitude: string;
  longitude: string;
  state: string;
  lga: string;
  customer_pickup: boolean;
  state_region: number | null;
  is_active: boolean;
}): Promise<SenderState> {
  if (!input.name.trim()) {
    return { fieldErrors: { name: "A pickup location needs a name." } };
  }
  if (!input.address.trim()) {
    return { fieldErrors: { address: "The rider needs the street address." } };
  }
  if (input.customer_pickup && input.state_region === null) {
    // Pre-check for a friendlier inline message; the serializer enforces it too.
    return { fieldErrors: { state_region: "Pick the store's state — customers are matched by state." } };
  }
  const body = {
    name: input.name.trim(),
    phone: input.phone.trim(),
    address: input.address.trim(),
    locality: input.locality.trim(),
    latitude: input.latitude.trim(),
    longitude: input.longitude.trim(),
    state: input.state.trim(),
    lga: input.lga.trim(),
    customer_pickup: input.customer_pickup,
    state_region: input.state_region,
    is_active: input.is_active,
  };
  try {
    if (input.id === null) {
      await fetchWithAuth("/admin/sender-locations/", { method: "POST", body });
    } else {
      await fetchWithAuth(`/admin/sender-locations/${input.id}/`, { method: "PATCH", body });
    }
  } catch (e) {
    return senderFieldErrors(e);
  }
  revalidatePath(PAGE);
  return { savedAt: Date.now() };
}

/** The backend refuses the DELETE once any shipment was quoted from the row
 * (deactivate instead); that message is surfaced verbatim. */
export async function deleteSenderLocationAction(input: {
  id: number;
}): Promise<SenderState> {
  try {
    await fetchWithAuth(`/admin/sender-locations/${input.id}/`, { method: "DELETE" });
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    const detail = (e.data as { detail?: string } | undefined)?.detail;
    return { message: detail ?? "That pickup location could not be deleted." };
  }
  revalidatePath(PAGE);
  return { savedAt: Date.now() };
}
