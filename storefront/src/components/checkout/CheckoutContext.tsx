"use client";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

/** Steps are numbered 1..5: 1 SignIn, 2 Address, 3 Delivery, 4 Payment, 5 Review. */
export const TOTAL_STEPS = 5;

export interface CheckoutSelections {
  userEmail?: string;
  addressId?: number;
  /** Short "line1, city" display string for the step-2 summary line — set via
   * `complete(2, { addressDisplay })`'s patch, never via `setAddress` (which only
   * knows the id). Purely cosmetic; place-order only needs `addressId`. */
  addressDisplay?: string;
  deliveryOptionId?: number;
  /** Short "name — price" display string for the step-3 summary line — set via
   * `complete(3, { deliveryDisplay })`'s patch, mirroring `addressDisplay`. Purely
   * cosmetic; place-order only needs `deliveryOptionId`. */
  deliveryDisplay?: string;
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
    setSelections((prev) => ({ ...prev, addressId, deliveryOptionId: undefined }));
    setCompleted((prev) => {
      if (!prev.has(3)) return prev;
      const next = new Set(prev);
      next.delete(3);
      return next;
    });
  }, []);

  const value = useMemo<CheckoutContextValue>(
    () => ({ currentStep, completed, selections, open, complete, setSelection, setAddress }),
    [currentStep, completed, selections, open, complete, setSelection, setAddress]
  );

  return <CheckoutContext.Provider value={value}>{children}</CheckoutContext.Provider>;
}

export function useCheckout(): CheckoutContextValue {
  const ctx = useContext(CheckoutContext);
  if (!ctx) throw new Error("useCheckout must be used within a CheckoutProvider");
  return ctx;
}
