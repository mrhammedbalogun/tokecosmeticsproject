"use server";

/**
 * The three decisions on a payout request.
 *
 * Each one is a single POST to an endpoint that carries its own scope — `referrals.manage`
 * for approve and reject, `referrals.pay` (Owner and Manager) for mark-paid. Nothing is
 * pre-checked here beyond an empty-field message: the backend services own the state
 * machine, and a second copy of "may this be rejected?" in the browser is a copy that
 * will disagree with the first one eventually.
 *
 * A 409 means somebody else already decided this row while the page was open. That is a
 * normal event on a queue two people work at month end, not an error — it is surfaced as
 * the sentence it is, and the revalidate below pulls the row's real state back.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

const PAGE = "/referrals";

export interface PayoutActionState {
  savedAt?: number;
  message?: string | null;
}

function payoutError(e: unknown, fallback: string): PayoutActionState {
  if (!(e instanceof ApiError)) return { message: "The API is not responding." };
  const data = e.data as { detail?: string; error?: string } | undefined;
  if (e.status === 403) {
    // Generic on purpose: this mapper serves all three actions, and the old copy
    // ("…is the Owner's") was wrong twice — it fired on approve/reject too, and
    // `referrals.pay` is Owner AND Manager (rbac.py, Hammed's ruling 2026-08-15).
    return { message: "Your role cannot do that." };
  }
  // The service's own sentence is better than anything invented here: it knows whether
  // the row was already paid, already rejected, or never open.
  return { message: data?.detail ?? fallback };
}

async function post(path: string, body: Record<string, unknown>, fallback: string) {
  try {
    await fetchWithAuth(path, { method: "POST", body });
  } catch (e) {
    // Revalidate on FAILURE too, not just success. The refusal that matters is the 409
    // (somebody else decided the row while this page was open), and the sentence alone
    // left the stale card sitting there with live buttons — on the screen staff copy
    // account numbers from. Re-reading the queue replaces it with the row's real state.
    revalidatePath(PAGE);
    return payoutError(e, fallback);
  }
  revalidatePath(PAGE);
  return { savedAt: Date.now() };
}

export async function approvePayoutAction(input: {
  id: number;
  adminNote: string;
}): Promise<PayoutActionState> {
  return post(
    `/admin/referral-payouts/${input.id}/approve/`,
    { admin_note: input.adminNote.trim() },
    "That payout could not be approved.",
  );
}

export async function rejectPayoutAction(input: {
  id: number;
  customerMessage: string;
  adminNote: string;
}): Promise<PayoutActionState> {
  // Checked here as well as at the serializer, only so the person gets the message
  // beside the box rather than as a form error after a round trip.
  if (!input.customerMessage.trim()) {
    return { message: "Tell the customer why — they see this on their payouts page." };
  }
  return post(
    `/admin/referral-payouts/${input.id}/reject/`,
    {
      customer_message: input.customerMessage.trim(),
      admin_note: input.adminNote.trim(),
    },
    "That payout could not be rejected.",
  );
}

export async function markPayoutPaidAction(input: {
  id: number;
  reference: string;
  adminNote: string;
}): Promise<PayoutActionState> {
  if (!input.reference.trim()) {
    return { message: "Record the bank's transfer reference — it is the receipt." };
  }
  return post(
    `/admin/referral-payouts/${input.id}/mark-paid/`,
    { reference: input.reference.trim(), admin_note: input.adminNote.trim() },
    "That payout could not be marked paid.",
  );
}
