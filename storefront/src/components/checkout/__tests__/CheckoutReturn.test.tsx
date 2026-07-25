import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const verifyPayment = vi.fn();
vi.mock("@/lib/payment-verify", () => ({ verifyPayment: (r: string) => verifyPayment(r) }));

import { CheckoutReturn } from "@/components/checkout/CheckoutReturn";

beforeEach(() => {
  replace.mockClear();
  verifyPayment.mockReset();
});

describe("CheckoutReturn", () => {
  it("routes to confirmation once verify reports succeeded", async () => {
    verifyPayment.mockResolvedValue({
      ok: true,
      orderNumber: "TC-88",
      paymentStatus: "succeeded",
      orderStatus: "processing",
    });
    render(<CheckoutReturn reference="TC-ref-88" pollDelayMs={0} />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/checkout/confirmation/TC-88"));
    expect(verifyPayment).toHaveBeenCalledTimes(1);
  });

  it("shows a retry state on a failed payment", async () => {
    verifyPayment.mockResolvedValue({
      ok: true,
      orderNumber: "TC-88",
      paymentStatus: "failed",
      orderStatus: "pending_payment",
    });
    render(<CheckoutReturn reference="TC-ref-88" pollDelayMs={0} />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/didn.t go through/i));
    expect(replace).not.toHaveBeenCalled();
    // A definitive failure is terminal — no point burning the remaining polls.
    expect(verifyPayment).toHaveBeenCalledTimes(1);
  });

  it("keeps polling while pending and routes as soon as it clears", async () => {
    verifyPayment
      .mockResolvedValueOnce({ ok: true, orderNumber: "TC-88", paymentStatus: "pending", orderStatus: "pending_payment" })
      .mockResolvedValueOnce({ ok: true, orderNumber: "TC-88", paymentStatus: "succeeded", orderStatus: "processing" });
    render(<CheckoutReturn reference="TC-ref-88" pollDelayMs={0} maxPolls={5} />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/checkout/confirmation/TC-88"));
    expect(verifyPayment).toHaveBeenCalledTimes(2);
  });

  it("falls back to an email-us message when still pending after the max polls", async () => {
    verifyPayment.mockResolvedValue({
      ok: true,
      orderNumber: "TC-88",
      paymentStatus: "pending",
      orderStatus: "pending_payment",
    });
    render(<CheckoutReturn reference="TC-ref-88" pollDelayMs={0} maxPolls={3} />);
    await waitFor(() => expect(screen.getByText(/confirming your payment/i)).toBeInTheDocument());
    expect(verifyPayment).toHaveBeenCalledTimes(3);
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows an error when no reference is present", () => {
    render(<CheckoutReturn reference="" pollDelayMs={0} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(verifyPayment).not.toHaveBeenCalled();
  });
});
