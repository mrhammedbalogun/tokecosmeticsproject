"use server";

/** Business Decisions writes (2026-08-27). `decisions.manage` — Owner AND Manager,
 * deliberately one notch wider than the Owner-only tax screens: tax is a legal position,
 * the referral percentages are a commercial one and the Manager makes it.
 *
 * Every write is audited on the backend with the before and after value. That audit row
 * is the only record of who moved a published term and when — the table itself keeps no
 * history, because each number is snapshotted onto the commissions and orders that used
 * it the moment they are created. */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface DecisionsSaveState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
}

function fieldErrorsFrom(e: ApiError): DecisionsSaveState {
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

/** The backend serializer is the real boundary; this only produces a friendlier inline
 * message than a round trip would. Note what is NOT rejected here: 0. Setting either
 * percentage to zero switches that half of the programme off without tearing anything
 * out, and it is a legitimate thing to want. */
function badPercent(raw: string, label: string): string | null {
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0 || value > 100) {
    return `${label} is a percentage between 0 and 100.`;
  }
  return null;
}

export async function saveBusinessDecisionsAction(input: {
  referrer_commission_percent: string;
  customer_discount_percent: string;
  customer_discount_first_order_only: boolean;
}): Promise<DecisionsSaveState> {
  const fieldErrors: Record<string, string> = {};
  const commissionError = badPercent(input.referrer_commission_percent, "Commission");
  if (commissionError) fieldErrors.referrer_commission_percent = commissionError;
  const discountError = badPercent(input.customer_discount_percent, "The customer discount");
  if (discountError) fieldErrors.customer_discount_percent = discountError;
  if (Object.keys(fieldErrors).length) return { fieldErrors };

  try {
    await fetchWithAuth("/admin/business-decisions/", {
      method: "PATCH",
      body: {
        referrer_commission_percent: input.referrer_commission_percent,
        customer_discount_percent: input.customer_discount_percent,
        customer_discount_first_order_only: input.customer_discount_first_order_only,
      },
    });
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    return fieldErrorsFrom(e);
  }
  revalidatePath("/business-decisions");
  return { savedAt: Date.now() };
}
