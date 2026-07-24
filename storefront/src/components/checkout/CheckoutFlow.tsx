"use client";
import Link from "next/link";
import { useCart } from "@/hooks/useCart";
import { CheckoutProvider, useCheckout } from "@/components/checkout/CheckoutContext";
import { StepShell } from "@/components/checkout/StepShell";
import { OrderSummary } from "@/components/checkout/OrderSummary";
import { SignInStep } from "@/components/checkout/SignInStep";
import { AddressStep } from "@/components/checkout/AddressStep";

const STEP_TITLES = ["Sign in", "Address", "Delivery", "Payment", "Review"] as const;

/** Module-scoped (not nested in CheckoutFlow) — eslint's react-hooks/static-components
 * rule flags components declared inside a render function; see OrderSummary.tsx's Row
 * for the same pattern.
 *
 * TODO(Plan-14 Task 8..10): replace StepStub with the real <DeliveryStep/>,
 * <PaymentStep/>, <ReviewStep/> components. Each stub just calls `onContinue`
 * with a token selection patch so downstream steps (and this shell) have
 * something non-empty to work with in the meantime. Step 1 (Sign in) is the real
 * <SignInStep/> (Task 6); step 2 (Address) is the real <AddressStep/> (Task 7). */
function StepStub({ step, label, onContinue }: { step: number; label: string; onContinue: () => void }) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">[Step {step} — built in Task {step + 5}]</p>
      <button
        type="button"
        onClick={onContinue}
        className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong"
      >
        Continue{label ? ` (${label})` : ""}
      </button>
    </div>
  );
}

/** Inner flow — needs useCheckout(), so it must render underneath CheckoutProvider. */
function CheckoutSteps() {
  const { currentStep, completed, complete, open, selections } = useCheckout();

  // Token patches so later stub steps (and CheckoutContext's own invalidation
  // logic) have something to chew on before the real steps land in Tasks 8-10.
  // Steps 1-2 no longer need a patch here — SignInStep/AddressStep complete
  // themselves.
  const stepPatches: Array<Record<string, unknown> | undefined> = [
    undefined,
    undefined,
    { deliveryOptionId: 0 },
    { paymentGateway: "stub" },
    undefined,
  ];

  const summaries: Record<number, string> = {
    1: `Signed in as ${selections.userEmail ?? ""}`,
    2: selections.addressDisplay ?? "Address selected",
  };

  return (
    <div className="space-y-4">
      {STEP_TITLES.map((title, i) => {
        const step = i + 1;
        return (
          <StepShell
            key={step}
            step={step}
            title={title}
            current={currentStep === step}
            complete={completed.has(step)}
            summary={summaries[step] ?? "Completed"}
            onChange={() => open(step)}
          >
            {step === 1 ? (
              <SignInStep />
            ) : step === 2 ? (
              <AddressStep />
            ) : (
              <StepStub step={step} label={title} onContinue={() => complete(step, stepPatches[i])} />
            )}
          </StepShell>
        );
      })}
    </div>
  );
}

/** Checkout page host. Wraps the step machine (CheckoutProvider) around the 5
 * StepShells and the order summary aside. */
export function CheckoutFlow() {
  const { cart, isLoading } = useCart();

  if (isLoading) {
    return <p className="mt-8 text-muted">Loading checkout…</p>;
  }

  // Empty-cart gate: gated purely on cart.items.length for now — there's no
  // order-in-flight signal yet. A real order navigates to the confirmation page
  // (Task 10/11 own that redirect), so a brief flash of this state right after
  // placing an order isn't a concern in this task.
  if (cart.items.length === 0) {
    return (
      <div className="mt-10 rounded-[var(--radius-card)] border border-line bg-surface p-10 text-center">
        <p className="text-muted">Your bag is empty.</p>
        <Link
          href="/products"
          className="mt-4 inline-block rounded-[var(--radius-card)] bg-accent px-6 py-3 text-surface transition-colors hover:bg-accent-strong"
        >
          Continue shopping
        </Link>
      </div>
    );
  }

  return (
    <CheckoutProvider>
      <div className="mt-8 grid gap-8 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <CheckoutSteps />
        </div>
        <div className="lg:sticky lg:top-24 lg:self-start">
          <div className="rounded-[var(--radius-card)] border border-line bg-surface p-5">
            <OrderSummary totals={null} fallbackSubtotal={cart.subtotal} currency={cart.currency} />
          </div>
        </div>
      </div>
    </CheckoutProvider>
  );
}
