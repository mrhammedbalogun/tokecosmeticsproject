"use server";

/** Coupon writes (Plan-19b). `marketing.manage`. */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface CouponState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
}

function fail(e: unknown, fallback: string): CouponState {
  if (!(e instanceof ApiError)) return { message: "The API is not responding." };
  const data = e.data as Record<string, unknown> | undefined;
  const fieldErrors: Record<string, string> = {};
  for (const [key, value] of Object.entries(data ?? {})) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[key] = first;
  }
  return Object.keys(fieldErrors).length ? { fieldErrors } : { message: fallback };
}

export async function createCouponAction(input: {
  code: string;
  type: "percent" | "fixed" | "free_shipping";
  value: string;
  currency: string;
  min_subtotal: string;
  usage_limit: string;
  ends_at: string;
}): Promise<CouponState> {
  const code = input.code.trim().toUpperCase();
  if (!code) return { fieldErrors: { code: "A coupon needs a code." } };
  // Mirrors the serializer's rule so the message is legible rather than a bare 400: a
  // fixed-amount coupon with no currency can never be compared to a cart total.
  if (input.type === "fixed" && !input.currency) {
    return { fieldErrors: { currency: "A fixed-amount coupon needs a currency." } };
  }

  try {
    await fetchWithAuth("/admin/coupons/", {
      method: "POST",
      body: {
        code,
        type: input.type,
        value: input.type === "free_shipping" ? "0" : input.value || "0",
        currency: input.type === "fixed" ? input.currency : null,
        min_subtotal: input.min_subtotal || "0",
        usage_limit: input.usage_limit ? Number(input.usage_limit) : null,
        ends_at: input.ends_at || null,
      },
    });
  } catch (e) {
    return fail(e, "That coupon could not be created.");
  }
  revalidatePath("/coupons");
  return { savedAt: Date.now() };
}

export async function setCouponActiveAction(id: number, isActive: boolean): Promise<CouponState> {
  try {
    await fetchWithAuth(`/admin/coupons/${id}/`, {
      method: "PATCH",
      body: { is_active: isActive },
    });
  } catch (e) {
    return fail(e, "That coupon could not be changed.");
  }
  revalidatePath("/coupons");
  return { savedAt: Date.now() };
}
