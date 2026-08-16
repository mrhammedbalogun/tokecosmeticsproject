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

interface BankAccountFields {
  bank_name: string;
  account_name: string;
  account_number: string;
  /** [label, value] pairs, order preserved — keys become the labels customers read. */
  extra: [string, string][];
  description: string;
  instructions: string;
  is_active: boolean;
}

/** Shared validation + payload shaping for create and save. Returns field errors, or
 * the request body ready to send. */
function bankAccountBody(
  input: BankAccountFields,
): { fieldErrors: Record<string, string> } | { body: Record<string, unknown> } {
  const number = input.account_number.trim();
  if (!number) {
    return { fieldErrors: { account_number: "Customers need a number to pay into." } };
  }
  if (!input.bank_name.trim() || !input.account_name.trim()) {
    return { fieldErrors: { bank_name: "The bank and account name both appear at checkout." } };
  }
  const extra: Record<string, string> = {};
  for (const [label, value] of input.extra) {
    if (!label.trim()) continue; // an unnamed row is an unfinished row — drop it
    if (label.trim() in extra) {
      return { fieldErrors: { extra: `"${label.trim()}" appears twice — labels must be unique.` } };
    }
    extra[label.trim()] = value.trim();
  }
  return {
    body: {
      bank_name: input.bank_name.trim(),
      account_name: input.account_name.trim(),
      account_number: number,
      extra,
      description: input.description,
      instructions: input.instructions,
      is_active: input.is_active,
    },
  };
}

export async function saveBankAccountAction(
  input: BankAccountFields & { id: number },
): Promise<ConfigState> {
  const shaped = bankAccountBody(input);
  if ("fieldErrors" in shaped) return shaped;

  try {
    await fetchWithAuth(`/admin/bank-accounts/${input.id}/`, {
      method: "PATCH",
      body: shaped.body,
    });
  } catch (e) {
    return fail(e, "That account could not be saved.");
  }
  revalidatePath("/settings/payments");
  return { savedAt: Date.now() };
}

/** Give a market its account — the missing half of "enable bank transfer here". The
 * currency comes from the market's gateway rows (the backend enforces it matches the
 * country anyway), so the form never asks. */
export async function createBankAccountAction(
  input: BankAccountFields & { country: string; currency: string },
): Promise<ConfigState> {
  const shaped = bankAccountBody(input);
  if ("fieldErrors" in shaped) return shaped;

  try {
    await fetchWithAuth("/admin/bank-accounts/", {
      method: "POST",
      body: { ...shaped.body, country: input.country, currency: input.currency },
    });
  } catch (e) {
    return fail(e, "That account could not be created.");
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

/** Offer a gateway in a market it never had. Always lands switched OFF — adding and
 * going live are two separate deliberate acts. */
export async function addGatewayAction(input: {
  country: string;
  gateway: string;
  sort_order: number;
}): Promise<ConfigState> {
  try {
    await fetchWithAuth("/admin/payment-gateways/", {
      method: "POST",
      body: {
        country: input.country,
        gateway: input.gateway,
        is_active: false,
        sort_order: input.sort_order,
      },
    });
  } catch (e) {
    return fail(e, "That method could not be added.");
  }
  revalidatePath("/settings/payments");
  return { savedAt: Date.now() };
}

/** "This market never offered this" — coherent to say (past orders keep their gateway
 * name), which is why DELETE is allowed here and not on bank accounts. */
export async function removeGatewayAction(id: number): Promise<ConfigState> {
  try {
    await fetchWithAuth(`/admin/payment-gateways/${id}/`, { method: "DELETE" });
  } catch (e) {
    return fail(e, "That method could not be removed.");
  }
  revalidatePath("/settings/payments");
  return { savedAt: Date.now() };
}

/** Persist a market's checkout menu order. Sequential PATCHes, smallest set the client
 * computed; not atomic, but each write is idempotent and a retry converges. */
export async function reorderGatewaysAction(
  updates: { id: number; sort_order: number }[],
): Promise<ConfigState> {
  try {
    for (const u of updates) {
      await fetchWithAuth(`/admin/payment-gateways/${u.id}/`, {
        method: "PATCH",
        body: { sort_order: u.sort_order },
      });
    }
  } catch (e) {
    return fail(e, "The order could not be saved.");
  }
  revalidatePath("/settings/payments");
  return { savedAt: Date.now() };
}
