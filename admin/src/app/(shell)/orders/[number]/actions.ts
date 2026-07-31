"use server";

/**
 * Every write on the order desk. Server Functions, like all authenticated writes here:
 * they get Next's Origin/Host check for free and may persist a rotated token, which a
 * Server Component may not.
 *
 * ── THESE MOVE MONEY, SO NONE OF THEM GUESSES ───────────────────────────────────────
 *
 * Each one forwards the backend's own message rather than inventing a friendlier one. On
 * this surface the backend's sentences are the specific ones — "expected 2000.00, received
 * 2500.00", "that bank reference has already been used" — and replacing them with
 * "something went wrong" would remove exactly the information the decision needs.
 *
 * `revalidatePath` on the order after every successful write: this page has no unsaved
 * form state to lose (unlike the product editor), and after confirming a payment the
 * status, the timeline and the payment block have all moved.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

/** Interpolated into a URL path, so its shape is checked before it gets there. */
const NUMBER = /^[A-Za-z0-9_-]+$/;

export interface WriteState {
  error?: string;
  /** Set when the backend named a machine-readable case the UI must react to. */
  code?: string;
  /** Populated for an amount discrepancy — both numbers, so the UI can show the delta. */
  expected?: string;
  received?: string;
  success?: string;
}

function fail(e: unknown, fallback: string): WriteState {
  if (!(e instanceof ApiError)) throw e;
  const data = (e.data ?? {}) as Record<string, unknown>;

  if (e.status === 403) {
    return { error: "Your role does not allow that." };
  }
  // The two overrides. Both carry a `code` the UI switches on, and the discrepancy also
  // carries the numbers — returned by the endpoint precisely so a person can decide
  // rather than just be refused (payments/views.py:263-267).
  if (typeof data.code === "string") {
    return {
      error: typeof data.detail === "string" ? data.detail : fallback,
      code: data.code,
      expected: typeof data.expected === "string" ? data.expected : undefined,
      received: typeof data.received === "string" ? data.received : undefined,
    };
  }
  if (typeof data.detail === "string") return { error: data.detail };
  for (const value of Object.values(data)) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") return { error: first };
  }
  return { error: fallback };
}

async function write<T>(number: string, path: string, init: {
  method: string;
  body?: unknown;
}): Promise<T> {
  return fetchWithAuth<T>(`/admin/orders/${number}${path}`, init);
}

function guard(number: string): WriteState | null {
  return NUMBER.test(number) ? null : { error: "That order could not be identified." };
}

// --- lifecycle -----------------------------------------------------------------------

export async function transitionAction(input: {
  number: string;
  toStatus: string;
  message: string;
}): Promise<WriteState> {
  const bad = guard(input.number);
  if (bad) return bad;

  try {
    await write(input.number, "/transition/", {
      method: "POST",
      body: { to_status: input.toStatus, message: input.message },
    });
  } catch (e) {
    return fail(e, "That move was refused.");
  }
  revalidatePath(`/orders/${input.number}`);
  revalidatePath("/orders");
  return { success: `Moved to ${input.toStatus.replace(/_/g, " ")}.` };
}

export async function trackingAction(input: {
  number: string;
  carrier: string;
  trackingNumber: string;
}): Promise<WriteState> {
  const bad = guard(input.number);
  if (bad) return bad;
  if (!input.carrier.trim() || !input.trackingNumber.trim()) {
    return { error: "Both a carrier and a tracking number are needed." };
  }

  try {
    await write(input.number, "/tracking/", {
      method: "PATCH",
      body: {
        tracking_carrier: input.carrier.trim(),
        tracking_number: input.trackingNumber.trim(),
      },
    });
  } catch (e) {
    return fail(e, "The tracking details could not be saved.");
  }
  revalidatePath(`/orders/${input.number}`);
  // Recording tracking does NOT email the customer — moving the order to `shipped` does
  // (AdminOrderTrackingView's own docstring). Said here so the copy can say it too.
  return { success: "Tracking saved. The customer is told when you mark it shipped." };
}

export async function noteAction(input: {
  number: string;
  note: string;
}): Promise<WriteState> {
  const bad = guard(input.number);
  if (bad) return bad;

  try {
    await write(input.number, "/note/", {
      method: "PATCH",
      body: { admin_note: input.note },
    });
  } catch (e) {
    return fail(e, "The note could not be saved.");
  }
  revalidatePath(`/orders/${input.number}`);
  return { success: "Note saved." };
}

export async function resolveReviewAction(input: { number: string }): Promise<WriteState> {
  const bad = guard(input.number);
  if (bad) return bad;

  try {
    await write(input.number, "/resolve-review/", { method: "POST" });
  } catch (e) {
    return fail(e, "The flag could not be cleared.");
  }
  revalidatePath(`/orders/${input.number}`);
  revalidatePath("/orders");
  // Worth saying: clearing the flag moves no money. It is a note being taken down, not a
  // problem being solved, and the endpoint's own docstring makes the same point.
  return { success: "Flag cleared. No money moved." };
}

// --- money ---------------------------------------------------------------------------

export async function confirmReceiptAction(input: {
  number: string;
  amountReceived: string;
  bankReference: string;
  note: string;
  acceptDiscrepancy: boolean;
  allowDuplicateReference: boolean;
}): Promise<WriteState> {
  const bad = guard(input.number);
  if (bad) return bad;

  const amount = input.amountReceived.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(amount) || Number(amount) <= 0) {
    return { error: "Enter the amount received, like 2000 or 2000.00." };
  }

  // NORMALISED BEFORE SENDING. The duplicate-reference guard is an exact match
  // (payments/services.py:318), so "REF 123", "ref123" and " REF123 " are three different
  // references to it — and a single space would defeat the cheapest control the system has
  // against shipping goods twice against one transfer. This changes what is SUBMITTED,
  // never what the backend accepts.
  const reference = input.bankReference.trim().replace(/\s+/g, " ").toUpperCase();
  if (!reference) return { error: "The bank reference is what stops one transfer paying twice." };

  try {
    await write(input.number, "/confirm-payment/", {
      method: "POST",
      body: {
        amount_received: amount,
        bank_reference: reference,
        note: input.note,
        accept_discrepancy: input.acceptDiscrepancy,
        allow_duplicate_reference: input.allowDuplicateReference,
      },
    });
  } catch (e) {
    return fail(e, "The payment could not be confirmed.");
  }
  revalidatePath(`/orders/${input.number}`);
  revalidatePath("/orders");
  return { success: "Payment confirmed." };
}

export async function gatewayRefundAction(input: {
  number: string;
  amount: string;
  reason: string;
  restock: boolean;
  paymentId: number;
}): Promise<WriteState> {
  const bad = guard(input.number);
  if (bad) return bad;
  if (!/^\d+(\.\d{1,2})?$/.test(input.amount.trim()) || Number(input.amount) <= 0) {
    return { error: "Enter an amount to refund, like 500 or 500.00." };
  }

  try {
    await write(input.number, "/refunds/", {
      method: "POST",
      body: {
        amount: input.amount.trim(),
        reason: input.reason,
        restock: input.restock,
        payment_id: input.paymentId,
      },
    });
  } catch (e) {
    return fail(e, "The refund could not be sent.");
  }
  revalidatePath(`/orders/${input.number}`);
  revalidatePath("/orders");
  return { success: "Refund sent to the gateway." };
}

export async function manualRefundAction(input: {
  number: string;
  amount: string;
  bankReference: string;
  note: string;
  restock: boolean;
}): Promise<WriteState> {
  const bad = guard(input.number);
  if (bad) return bad;
  if (!/^\d+(\.\d{1,2})?$/.test(input.amount.trim()) || Number(input.amount) <= 0) {
    return { error: "Enter the amount you sent, like 500 or 500.00." };
  }
  const reference = input.bankReference.trim().replace(/\s+/g, " ").toUpperCase();
  if (!reference) return { error: "Record the bank reference of the transfer you sent." };

  try {
    await write(input.number, "/manual-refund/", {
      method: "POST",
      body: {
        amount: input.amount.trim(),
        bank_reference: reference,
        note: input.note,
        restock: input.restock,
      },
    });
  } catch (e) {
    return fail(e, "The refund could not be recorded.");
  }
  revalidatePath(`/orders/${input.number}`);
  revalidatePath("/orders");
  // The wording matters: this RECORDS money the operator already sent by hand. It does not
  // move any.
  return { success: "Refund recorded. No money was moved by this — you sent it." };
}
