import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PaymentMethodSwitch } from "@/components/checkout/PaymentMethodSwitch";

const METHODS_URL = "/api/checkout/payment-methods";
const PAY_URL = "/api/checkout/pay";

const orig = global.fetch;
afterEach(() => {
  global.fetch = orig;
  vi.restoreAllMocks();
});

type Route = { status: number; body: unknown };
function mockFetch(routes: Record<string, Route>) {
  const f = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const key = Object.keys(routes).find((k) => url.startsWith(k));
    if (!key) return Promise.reject(new Error(`unexpected fetch: ${url}`));
    const route = routes[key];
    return Promise.resolve(
      new Response(JSON.stringify(route.body), {
        status: route.status,
        headers: { "content-type": "application/json" },
      })
    );
  });
  global.fetch = f as unknown as typeof fetch;
  return f;
}

const THREE_METHODS = {
  status: 200,
  body: [
    { gateway: "paystack", sort_order: 1 },
    { gateway: "flutterwave", sort_order: 2 },
    { gateway: "bank_transfer", sort_order: 3 },
  ],
};

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("PaymentMethodSwitch", () => {
  it("offers the other methods but not the one that just failed", async () => {
    mockFetch({ [METHODS_URL]: THREE_METHODS });
    render(
      <PaymentMethodSwitch
        orderNumber="TC-300"
        currentGateway="paystack"
        onRelaunch={vi.fn()}
        onBankDetails={vi.fn()}
      />
    );
    await waitFor(() => expect(screen.getAllByRole("button")).toHaveLength(2));
    const names = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    expect(names.some((n) => n.includes("Card / Flutterwave"))).toBe(true);
    expect(names.some((n) => n.includes("Bank transfer"))).toBe(true);
    // The method that just failed is not offered back.
    expect(names.some((n) => n.includes("Card / Paystack"))).toBe(false);
  });

  it("re-opens payment on the chosen gateway and hands the new launch back", async () => {
    const onRelaunch = vi.fn();
    const f = mockFetch({
      [METHODS_URL]: THREE_METHODS,
      [PAY_URL]: {
        status: 200,
        body: {
          order_number: "TC-300",
          payment: { gateway: "flutterwave", action: "redirect", reference: "FLW-1", data: { redirect_url: "https://flw" } },
        },
      },
    });
    render(
      <PaymentMethodSwitch
        orderNumber="TC-300"
        currentGateway="paystack"
        onRelaunch={onRelaunch}
        onBankDetails={vi.fn()}
      />
    );
    await waitFor(() => expect(screen.getAllByRole("button")).toHaveLength(2));
    fireEvent.click(screen.getAllByRole("button")[0]);

    await waitFor(() =>
      expect(onRelaunch).toHaveBeenCalledWith({
        gateway: "flutterwave",
        reference: "FLW-1",
        orderNumber: "TC-300",
        data: { redirect_url: "https://flw" },
      })
    );
    const payCall = f.mock.calls.find((c) => String(c[0]) === PAY_URL)!;
    expect(JSON.parse((payCall[1] as RequestInit).body as string)).toMatchObject({
      order_number: "TC-300",
      payment_gateway: "flutterwave",
    });
  });

  it("routes a bank-transfer switch to the confirmation handoff, not the launcher", async () => {
    const onBankDetails = vi.fn();
    const onRelaunch = vi.fn();
    mockFetch({
      [METHODS_URL]: THREE_METHODS,
      [PAY_URL]: {
        status: 200,
        body: {
          order_number: "TC-300",
          payment: { gateway: "bank_transfer", action: "bank_details", reference: "TC-300", data: { display: { Bank: "GTB" } } },
        },
      },
    });
    render(
      <PaymentMethodSwitch
        orderNumber="TC-300"
        currentGateway="paystack"
        onRelaunch={onRelaunch}
        onBankDetails={onBankDetails}
      />
    );
    await waitFor(() => expect(screen.getAllByRole("button")).toHaveLength(2));
    fireEvent.click(screen.getAllByRole("button")[1]);

    await waitFor(() =>
      expect(onBankDetails).toHaveBeenCalledWith("TC-300", { display: { Bank: "GTB" } })
    );
    expect(onRelaunch).not.toHaveBeenCalled();
  });

  it("shows a message when the order can no longer be paid", async () => {
    mockFetch({
      [METHODS_URL]: THREE_METHODS,
      [PAY_URL]: { status: 409, body: { error: "order_not_payable" } },
    });
    render(
      <PaymentMethodSwitch
        orderNumber="TC-300"
        currentGateway="paystack"
        onRelaunch={vi.fn()}
        onBankDetails={vi.fn()}
      />
    );
    await waitFor(() => expect(screen.getAllByRole("button")).toHaveLength(2));
    fireEvent.click(screen.getAllByRole("button")[0]);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/no longer/i));
  });

  it("reports when no other method is available rather than rendering an empty list", async () => {
    mockFetch({ [METHODS_URL]: { status: 200, body: [{ gateway: "paystack", sort_order: 1 }] } });
    render(
      <PaymentMethodSwitch
        orderNumber="TC-300"
        currentGateway="paystack"
        onRelaunch={vi.fn()}
        onBankDetails={vi.fn()}
      />
    );
    await waitFor(() => expect(screen.getByText(/no other payment method/i)).toBeInTheDocument());
  });
});
