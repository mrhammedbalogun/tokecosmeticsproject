"use server";

/** Money-config writes (Plan-19b). `settings.manage` — Owner only, enforced by Django.
 *
 * These two forms change where money lands and which methods a market offers. Neither had
 * any UI path before: `/django-admin/` is denied at the Apache vhost, so the fallback
 * Plan-09b named for the bank account did not exist.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface ConfigState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
}

function fail(e: unknown, fallback: string): ConfigState {
  if (!(e instanceof ApiError)) return { message: "The API is not responding." };
  const data = e.data as Record<string, unknown> | undefined;
  const fieldErrors: Record<string, string> = {};
  for (const [key, value] of Object.entries(data ?? {})) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[key] = first;
  }
  if (Object.keys(fieldErrors).length) return { fieldErrors };
  return { message: fallback };
}

export async function saveBankAccountAction(input: {
  id: number;
  bank_name: string;
  account_name: string;
  account_number: string;
  instructions: string;
  is_active: boolean;
}): Promise<ConfigState> {
  const number = input.account_number.trim();
  if (!number) {
    return { fieldErrors: { account_number: "Customers need a number to pay into." } };
  }
  if (!input.bank_name.trim() || !input.account_name.trim()) {
    return { fieldErrors: { bank_name: "The bank and account name both appear at checkout." } };
  }

  try {
    await fetchWithAuth(`/admin/bank-accounts/${input.id}/`, {
      method: "PATCH",
      body: {
        bank_name: input.bank_name.trim(),
        account_name: input.account_name.trim(),
        account_number: number,
        instructions: input.instructions,
        is_active: input.is_active,
      },
    });
  } catch (e) {
    return fail(e, "That account could not be saved.");
  }
  revalidatePath("/settings/payments");
  return { savedAt: Date.now() };
}

export async function setGatewayActiveAction(
  id: number,
  isActive: boolean,
): Promise<ConfigState> {
  try {
    await fetchWithAuth(`/admin/payment-gateways/${id}/`, {
      method: "PATCH",
      body: { is_active: isActive },
    });
  } catch (e) {
    return fail(e, "That gateway could not be changed.");
  }
  revalidatePath("/settings/payments");
  return { savedAt: Date.now() };
}
