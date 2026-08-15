"use server";

/**
 * The two things a referrer can DO: save the bank account their money goes to, and ask
 * for it.
 *
 * Server Functions rather than BFF route handlers, matching account/profile and
 * account/security: Next's Origin/Host CSRF check comes free, the forms work without
 * JavaScript, and `fetchWithAuth`'s silent 401→refresh→retry is allowed here (a Server
 * Function may write cookies, a Server Component may not — see lib/session.ts).
 *
 * Both revalidate `/account/referrals` on success. Without it the page is served from
 * the router cache and a customer who just requested a payout sees their old balance,
 * which reads exactly like the request failing.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

// Both pages, not just the one the form is on. A payout changes the balance the
// dashboard's wallet card shows AND the withdraw state the payouts page shows, and
// `revalidatePath` on a single path leaves the other rendering yesterday's number from
// the router cache — which reads exactly like the request having failed.
const PAGES = ["/account/referrals", "/account/referrals/payouts"] as const;

function revalidateReferralPages(): void {
  for (const path of PAGES) revalidatePath(path);
}

export interface PayoutMethodState {
  saved?: boolean;
  error?: string;
}

export interface PayoutRequestState {
  requested?: boolean;
  amount?: string;
  error?: string;
  /** The backend's stable refusal code, passed through so the form can decide whether to
   * re-open the terms checkbox rather than string-matching English. */
  code?: string;
}

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

/**
 * Turn an upstream failure into one sentence for the customer.
 *
 * `detail` from the referrals API is written to be shown — every ReferralError carries a
 * human sentence ("You need at least ₦20,000…"). DRF field errors are not, so those fall
 * back to the generic line rather than leaking `{"account_number": ["…"]}` into the UI.
 */
function messageFrom(e: unknown, fallback: string): { error: string; code?: string } {
  if (e instanceof ApiError) {
    const data = e.data as { detail?: unknown; error?: unknown } | undefined;
    const detail = typeof data?.detail === "string" ? data.detail : "";
    const code = typeof data?.error === "string" ? data.error : undefined;
    return { error: detail || fallback, code };
  }
  return { error: fallback };
}

export async function savePayoutMethodAction(
  _prev: PayoutMethodState,
  formData: FormData,
): Promise<PayoutMethodState> {
  const currency = field(formData, "currency");
  const bankName = field(formData, "bank_name");
  const accountName = field(formData, "account_name");
  const accountNumber = field(formData, "account_number");

  if (!currency) return { error: "Choose which currency this account is for." };
  if (!bankName) return { error: "Enter your bank's name." };
  if (!accountName) return { error: "Enter the account holder's name." };
  if (!accountNumber) return { error: "Enter your account number." };

  try {
    await fetchWithAuth("/me/referrals/payout-methods/", {
      method: "PUT",
      body: {
        currency,
        bank_name: bankName,
        account_name: accountName,
        account_number: accountNumber,
        // Optional per-market extras (sort code, routing number). Sent only when filled
        // so an empty box does not overwrite a stored value with "".
        extra: Object.fromEntries(
          (["sort_code", "routing_number", "iban", "swift"] as const)
            .map((key) => [key, field(formData, key)] as const)
            .filter(([, value]) => value !== ""),
        ),
      },
    });
  } catch (e) {
    return messageFrom(e, "We couldn't save those bank details — please try again.");
  }

  revalidateReferralPages();
  return { saved: true };
}

export async function requestPayoutAction(
  _prev: PayoutRequestState,
  formData: FormData,
): Promise<PayoutRequestState> {
  const currency = field(formData, "currency");
  if (!currency) return { error: "Choose a currency to withdraw." };

  try {
    const payout = await fetchWithAuth<{ amount_display: string }>(
      "/me/referrals/payouts/",
      {
        method: "POST",
        body: {
          currency,
          // An unticked checkbox is absent from FormData entirely, so this sends an
          // explicit boolean — the backend refuses a first payout without it, and
          // "absent" must not read as "agreed".
          accept_terms: formData.get("accept_terms") !== null,
        },
      },
    );
    revalidateReferralPages();
    return { requested: true, amount: payout.amount_display };
  } catch (e) {
    return messageFrom(e, "We couldn't submit that request — please try again.");
  }
}
