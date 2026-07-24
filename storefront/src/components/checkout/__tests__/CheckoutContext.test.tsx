import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CheckoutProvider, useCheckout } from "@/components/checkout/CheckoutContext";

/** Small harness exposing the checkout machine's state/actions as buttons/text so
 * the reducer-ish logic in CheckoutContext (address change invalidates delivery,
 * complete() advances to the next open step) gets a focused test independent of
 * the full CheckoutFlow UI. */
function Harness() {
  const { currentStep, completed, selections, complete, setAddress } = useCheckout();
  return (
    <div>
      <p data-testid="current">{currentStep}</p>
      <p data-testid="completed">{[...completed].sort().join(",")}</p>
      <p data-testid="addressId">{String(selections.addressId ?? "")}</p>
      <p data-testid="deliveryOptionId">{String(selections.deliveryOptionId ?? "")}</p>
      <button onClick={() => complete(1)}>complete-1</button>
      <button onClick={() => complete(2, { addressId: 7 })}>complete-2</button>
      <button onClick={() => complete(3, { deliveryOptionId: 42 })}>complete-3</button>
      <button onClick={() => setAddress(99)}>change-address</button>
    </div>
  );
}

function renderHarness() {
  return render(
    <CheckoutProvider>
      <Harness />
    </CheckoutProvider>
  );
}

describe("CheckoutContext", () => {
  it("starts on step 1 with nothing completed", () => {
    renderHarness();
    expect(screen.getByTestId("current")).toHaveTextContent("1");
    expect(screen.getByTestId("completed")).toHaveTextContent("");
  });

  it("complete() marks the step done, merges the patch, and advances to the next open step", () => {
    renderHarness();
    fireEvent.click(screen.getByText("complete-1"));
    expect(screen.getByTestId("completed")).toHaveTextContent("1");
    expect(screen.getByTestId("current")).toHaveTextContent("2");

    fireEvent.click(screen.getByText("complete-2"));
    expect(screen.getByTestId("completed")).toHaveTextContent("1,2");
    expect(screen.getByTestId("addressId")).toHaveTextContent("7");
    expect(screen.getByTestId("current")).toHaveTextContent("3");
  });

  it("setAddress clears the delivery selection and un-completes step 3", () => {
    renderHarness();
    fireEvent.click(screen.getByText("complete-1"));
    fireEvent.click(screen.getByText("complete-2"));
    fireEvent.click(screen.getByText("complete-3"));
    expect(screen.getByTestId("completed")).toHaveTextContent("1,2,3");
    expect(screen.getByTestId("deliveryOptionId")).toHaveTextContent("42");

    fireEvent.click(screen.getByText("change-address"));

    expect(screen.getByTestId("addressId")).toHaveTextContent("99");
    expect(screen.getByTestId("deliveryOptionId")).toHaveTextContent("");
    expect(screen.getByTestId("completed")).toHaveTextContent("1,2");
  });
});
