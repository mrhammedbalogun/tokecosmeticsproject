/** Bank-transfer details handoff (Plan-14 Task 10). The BFF's place-order response
 * carries the bank details ONCE, in `payment.data` — there is no endpoint to fetch
 * them again later. ReviewStep stashes them here right after a successful 201, keyed
 * by order number, and the confirmation page (Task 11) reads them back. sessionStorage
 * (not localStorage) is deliberate: this is a one-time, tab-scoped handoff, not
 * something that should linger across sessions or devices. */
export const BANK_HANDOFF_KEY = "toke-bank-handoff";

export interface BankDetailsData {
  display?: Record<string, string>;
  reference?: string;
  instructions?: string;
  [k: string]: unknown;
}

interface StoredHandoff {
  number: string;
  data: BankDetailsData;
}

export function stashBankHandoff(number: string, data: BankDetailsData): void {
  if (typeof sessionStorage === "undefined") return;
  const payload: StoredHandoff = { number, data };
  sessionStorage.setItem(BANK_HANDOFF_KEY, JSON.stringify(payload));
}

/** Returns the stashed data only if it was stashed for THIS order number — never a
 * stale handoff from a previous order. Null on absence, mismatch, corrupt JSON, or
 * SSR (no sessionStorage). */
export function readBankHandoff(number: string): BankDetailsData | null {
  if (typeof sessionStorage === "undefined") return null;
  const raw = sessionStorage.getItem(BANK_HANDOFF_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<StoredHandoff>;
    if (parsed && parsed.number === number && parsed.data) return parsed.data;
    return null;
  } catch {
    return null;
  }
}
