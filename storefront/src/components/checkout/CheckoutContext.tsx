"use client";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

/** Steps are numbered 1..5: 1 SignIn, 2 Address, 3 Delivery, 4 Payment, 5 Review. */
export const TOTAL_STEPS = 5;

/** The inline guest address exactly as the backend's GuestAddressSerializer wants it
 * (Plan-38) — POSTed to the guest delivery/quote/checkout endpoints, never saved. */
export type GuestAddressPayload = Record<string, unknown>;

export interface CheckoutSelections {
  userEmail?: string;
  /** Set when the shopper chose "Continue as guest" in step 1 (Plan-38). Its
   * presence IS the guest-mode flag every later step branches on. */
  guest?: { email: string; phone: string };
  /** The guest's validated inline address payload — the guest twin of `addressId`.
   * Validated server-side by the guest delivery-options call in AddressStep. */
  guestAddress?: GuestAddressPayload;
  addressId?: number;
  /** Short "line1, city" display string for the step-2 summary line — set via
   * `complete(2, { addressDisplay })`'s patch, never via `setAddress` (which only
   * knows the id). Purely cosmetic; place-order only needs `addressId`. */
  addressDisplay?: string;
  /** number for DeliveryOption rows, string ("pz:{pk}") for partner zones (Plan-39). */
  deliveryOptionId?: number | string;
  /** Short "name — price" display string for the step-3 summary line — set via
   * `complete(3, { deliveryDisplay })`'s patch, mirroring `addressDisplay`. Purely
   * cosmetic; place-order only needs `deliveryOptionId`. */
  deliveryDisplay?: string;
  /** The chosen GIG pickup centre (32b slice 4) — GIG's centre id, set only when
   * the selected delivery option is centre pickup; rides the quote and the
   * place-order payloads so the server prices the customer's actual centre. */
  gigCentreId?: number;
  /** The chosen Toke pickup store (Plan-40) — SenderLocation pk, set only when the
   * selected option is store pickup; rides place-order as `pickup_store_id`. */
  pickupStoreId?: number;
  paymentGateway?: string;
  note: string;
}

interface CheckoutContextValue {
  currentStep: number;
  completed: Set<number>;
  selections: CheckoutSelections;
  /** Set the open step (used by a step's "Change" button). Does not affect completion. */
  open: (step: number) => void;
  /** Merge `patch` into selections, mark `step` complete, and advance to the next
   * not-yet-completed step (or stay put if every step is already done). */
  complete: (step: number, patch?: Partial<CheckoutSelections>) => void;
  /** Shallow-merge into selections without touching the step machine. */
  setSelection: (patch: Partial<CheckoutSelections>) => void;
  /** Address changed: set it, and since a new address invalidates any already-picked
   * delivery option, clear it and un-complete step 3 (Delivery) so the shopper re-picks. */
  setAddress: (addressId: number) => void;
  /** Guest twin of setAddress (Plan-38): same delivery-invalidation rule, but the
   * address is the inline payload rather than a saved-address id. */
  setGuestAddress: (address: GuestAddressPayload) => void;
}

const CheckoutContext = createContext<CheckoutContextValue | null>(null);

/** Next open step after marking `step` done: the lowest-numbered step not in
 * `completed` (ignoring `step` itself, which the caller has just completed). If
 * every step is complete, stay on the current one. */
function nextOpenStep(completed: Set<number>, fallback: number): number {
  for (let s = 1; s <= TOTAL_STEPS; s++) {
    if (!completed.has(s)) return s;
  }
  return fallback;
}

export function CheckoutProvider({ children }: { children: ReactNode }) {
  const [currentStep, setCurrentStep] = useState(1);
  const [completed, setCompleted] = useState<Set<number>>(new Set());
  const [selections, setSelections] = useState<CheckoutSelections>({ note: "" });

  const open = useCallback((step: number) => {
    setCurrentStep(step);
  }, []);

  const complete = useCallback((step: number, patch?: Partial<CheckoutSelections>) => {
    if (patch) setSelections((prev) => ({ ...prev, ...patch }));
    setCompleted((prev) => {
      const next = new Set(prev);
      next.add(step);
      setCurrentStep(nextOpenStep(next, step));
      return next;
    });
  }, []);

  const setSelection = useCallback((patch: Partial<CheckoutSelections>) => {
    setSelections((prev) => ({ ...prev, ...patch }));
  }, []);

  const setAddress = useCallback((addressId: number) => {
    // A new address invalidates the delivery choice AND both pickup choices — the
    // centre list is sorted for (and priced from) the old address, and the store
    // list is the old address's STATE.
    setSelections((prev) => ({
      ...prev, addressId, deliveryOptionId: undefined,
      gigCentreId: undefined, pickupStoreId: undefined,
    }));
    setCompleted((prev) => {
      if (!prev.has(3)) return prev;
      const next = new Set(prev);
      next.delete(3);
      return next;
    });
  }, []);

  const setGuestAddress = useCallback((address: GuestAddressPayload) => {
    // Same rule as setAddress: a new address invalidates delivery + centre + store.
    setSelections((prev) => ({
      ...prev, guestAddress: address, deliveryOptionId: undefined,
      gigCentreId: undefined, pickupStoreId: undefined,
    }));
    setCompleted((prev) => {
      if (!prev.has(3)) return prev;
      const next = new Set(prev);
      next.delete(3);
      return next;
    });
  }, []);

  const value = useMemo<CheckoutContextValue>(
    () => ({
      currentStep, completed, selections, open, complete, setSelection,
      setAddress, setGuestAddress,
    }),
    [currentStep, completed, selections, open, complete, setSelection, setAddress, setGuestAddress]
  );

  return <CheckoutContext.Provider value={value}>{children}</CheckoutContext.Provider>;
}

export function useCheckout(): CheckoutContextValue {
  const ctx = useContext(CheckoutContext);
  if (!ctx) throw new Error("useCheckout must be used within a CheckoutProvider");
  return ctx;
}
