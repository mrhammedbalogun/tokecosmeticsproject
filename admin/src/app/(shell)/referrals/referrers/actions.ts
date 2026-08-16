"use server";

/**
 * Blocking a referrer, and moving a balance by hand.
 *
 * These are the two admin actions with NO customer-visible receipt. A rejected payout
 * emails the referrer; a block does not, and neither does ₦2,500 leaving their balance.
 * What keeps them honest is the reason each one forces somebody to type and the audit
 * row the backend writes — so both actions here refuse to send an empty reason rather
 * than letting the server discover it, purely so the message lands beside the field.
 *
 * Everything else is the backend's call. `add_adjustment` deliberately validates very
 * little (it is the escape hatch for cases the model did not anticipate), and a second
 * copy of that judgement in the browser would be a copy that disagrees.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

const PAGE = "/referrals/referrers";

export interface ReferrerActionState {
  savedAt?: number;
  message?: string | null;
}

function referrerError(e: unknown, fallback: string): ReferrerActionState {
  if (!(e instanceof ApiError)) return { message: "The API is not responding." };
  if (e.status === 403) {
    return { message: "Your role cannot do that." };
  }
  const data = e.data as { detail?: string; error?: string } | undefined;
  return { message: data?.detail ?? fallback };
}

export async function setReferrerBlockedAction(input: {
  id: number;
  blocked: boolean;
  reason: string;
}): Promise<ReferrerActionState> {
  // Required to block, ignored to unblock — the backend rule, mirrored here only so the
  // message appears next to the box.
  if (input.blocked && !input.reason.trim()) {
    return { message: "Say why. Somebody will ask in six months and it will not be you." };
  }
  try {
    await fetchWithAuth(`/admin/referrers/${input.id}/block/`, {
      method: "POST",
      body: { blocked: input.blocked, reason: input.reason.trim() },
    });
  } catch (e) {
    return referrerError(e, "That referrer could not be updated.");
  }
  revalidatePath(PAGE);
  return { savedAt: Date.now() };
}

export async function addAdjustmentAction(input: {
  id: number;
  currency: string;
  amount: string;
  kind: string;
  reason: string;
}): Promise<ReferrerActionState> {
  if (!input.reason.trim()) {
    return { message: "Say why — this row outlives everyone here." };
  }
  const amount = Number(input.amount);
  if (!Number.isFinite(amount) || amount === 0) {
    return { message: "Enter an amount. Negative takes money away, positive gives it." };
  }
  try {
    await fetchWithAuth(`/admin/referrers/${input.id}/adjust/`, {
      method: "POST",
      body: {
        currency: input.currency,
        // Sent as typed rather than reformatted: the backend quantises, and rounding it
        // twice in two places is how a kobo goes missing.
        amount: input.amount.trim(),
        kind: input.kind,
        reason: input.reason.trim(),
      },
    });
  } catch (e) {
    return referrerError(e, "That adjustment could not be saved.");
  }
  revalidatePath(PAGE);
  return { savedAt: Date.now() };
}
