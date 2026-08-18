"use server";

/** Tax settings writes (Plan-37). `settings.manage` — Owner-only, like the payout
 * account, because these change what every customer pays. */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface TaxSaveState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
}

function fieldErrorsFrom(e: ApiError): TaxSaveState {
  const data = e.data as Record<string, unknown> | undefined;
  const fieldErrors: Record<string, string> = {};
  for (const [key, value] of Object.entries(data ?? {})) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[key] = first;
  }
  return Object.keys(fieldErrors).length ? { fieldErrors } : { message: "That could not be saved." };
}

export async function saveTaxMasterSwitchAction(input: {
  charge_tax: boolean;
}): Promise<TaxSaveState> {
  try {
    await fetchWithAuth("/admin/tax/settings/", {
      method: "PATCH",
      body: { charge_tax: input.charge_tax },
    });
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    return fieldErrorsFrom(e);
  }
  revalidatePath("/settings/taxes");
  return { savedAt: Date.now() };
}

export async function saveTaxCountryAction(input: {
  code: string;
  charge_tax: boolean;
  tax_rate_percent: string;
  prices_include_tax: boolean;
  tax_applies_to_delivery: boolean;
  tax_label: string;
}): Promise<TaxSaveState> {
  // The backend serializer is the real boundary; these pre-checks only make
  // friendlier inline messages.
  const rate = Number(input.tax_rate_percent);
  if (!Number.isFinite(rate) || rate < 0 || rate > 100) {
    return { fieldErrors: { tax_rate_percent: "A tax rate is a percentage between 0 and 100." } };
  }
  if (!input.tax_label.trim()) {
    return { fieldErrors: { tax_label: "The tax line needs a name — customers see it at checkout." } };
  }
  try {
    await fetchWithAuth(`/admin/tax/countries/${input.code}/`, {
      method: "PATCH",
      body: {
        charge_tax: input.charge_tax,
        tax_rate_percent: input.tax_rate_percent,
        prices_include_tax: input.prices_include_tax,
        tax_applies_to_delivery: input.tax_applies_to_delivery,
        tax_label: input.tax_label.trim(),
      },
    });
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    return fieldErrorsFrom(e);
  }
  revalidatePath("/settings/taxes");
  return { savedAt: Date.now() };
}
