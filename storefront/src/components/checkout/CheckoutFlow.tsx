"use client";
import Link from "next/link";
import { useCart } from "@/hooks/useCart";
import { CheckoutProvider, useCheckout } from "@/components/checkout/CheckoutContext";
import { StepShell } from "@/components/checkout/StepShell";
import { OrderSummary } from "@/components/checkout/OrderSummary";
import { SignInStep } from "@/components/checkout/SignInStep";
import { AddressStep } from "@/components/checkout/AddressStep";
import { DeliveryStep } from "@/components/checkout/DeliveryStep";
import { PaymentStep } from "@/components/checkout/PaymentStep";
import { ReviewStep } from "@/components/checkout/ReviewStep";
import { paymentLabel } from "@/lib/payment-labels";

const STEP_TITLES = ["Sign in", "Address", "Delivery", "Payment", "Review"] as const;

/** Inner flow — needs useCheckout(), so it must render underneath CheckoutProvider. */
function CheckoutSteps() {
  const { currentStep, completed, open, selections } = useCheckout();

  const summaries: Record<number, string> = {
    1: `Signed in as ${selections.userEmail ?? ""}`,
    2: selections.addressDisplay ?? "Address selected",
    3: selections.deliveryDisplay ?? "Delivery selected",
    4: selections.paymentGateway ? paymentLabel(selections.paymentGateway).name : "Payment method selected",
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
            ) : step === 3 ? (
              <DeliveryStep />
            ) : step === 4 ? (
              <PaymentStep />
            ) : (
              <ReviewStep />
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
