import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const replace = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, refresh }) }));

const stashBankHandoff = vi.fn();
vi.mock("@/lib/bank-handoff", () => ({
  stashBankHandoff: (n: string, d: unknown) => stashBankHandoff(n, d),
}));

// The launcher drags in the real gateway SDK children (script loaders) — a marker
// stands in; PaymentLauncher has its own suite.
vi.mock("@/components/checkout/PaymentLauncher", () => ({
  PaymentLauncher: ({ launch }: { launch: { gateway: string; reference: string } }) => (
    <div data-testid="launcher">{launch.gateway}:{launch.reference}</div>
  ),
}));

import { PayAgain } from "@/components/checkout/PayAgain";

type Route = { status: number; body: unknown };
function mockFetch(routes: Record<string, Route>) {
  const f = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const route = routes[url];
    if (!route) return Promise.reject(new Error(`unexpected fetch: ${url}`));
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

const originalFetch = global.fetch;
beforeEach(() => {
  replace.mockClear();
  refresh.mockClear();
  stashBankHandoff.mockClear();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

const METHODS = [
  { gateway: "paystack", sort_order: 1, instructions: "" },
  { gateway: "bank_transfer", sort_order: 2, instructions: "" },
];

describe("PayAgain", () => {
  it("opens the picker for the ORDER's market and offers the current gateway back", async () => {
    const f = mockFetch({
      "/api/checkout/payment-methods?country=NG": { status: 200, body: METHODS },
    });
    render(<PayAgain orderNumber="TC-300" currentGateway="paystack" country="NG" />);

    fireEvent.click(screen.getByRole("button", { name: /pay now/i }));
    // excludeCurrent=false: retrying the same method is the most likely wish from an
    // order page — the current gateway must be in the list.
    await waitFor(() => screen.getByRole("button", { name: /paystack/i }));
    expect(screen.getByRole("button", { name: /bank transfer/i })).toBeInTheDocument();
    expect(f).toHaveBeenCalledWith("/api/checkout/payment-methods?country=NG");
  });

  it("an online choice posts to /api/checkout/pay and hands the envelope to the launcher", async () => {
    mockFetch({
      "/api/checkout/payment-methods?country=NG": { status: 200, body: METHODS },
      "/api/checkout/pay": {
        status: 200,
        body: {
          order_number: "TC-300",
          payment: { gateway: "paystack", action: "inline", reference: "TC-300-P7", data: {} },
        },
      },
    });
    render(<PayAgain orderNumber="TC-300" currentGateway="paystack" country="NG" />);
    fireEvent.click(screen.getByRole("button", { name: /pay now/i }));
    await waitFor(() => screen.getByRole("button", { name: /paystack/i }));
    fireEvent.click(screen.getByRole("button", { name: /paystack/i }));

    await waitFor(() => screen.getByTestId("launcher"));
    expect(screen.getByTestId("launcher")).toHaveTextContent("paystack:TC-300-P7");
  });

  it("a bank-transfer choice stashes the handoff and lands on the confirmation page", async () => {
    mockFetch({
      "/api/checkout/payment-methods?country=NG": { status: 200, body: METHODS },
      "/api/checkout/pay": {
        status: 200,
        body: {
          order_number: "TC-300",
          payment: {
            gateway: "bank_transfer", action: "bank_details", reference: "TC-300",
            data: { bank_name: "GTBank" },
          },
        },
      },
    });
    render(<PayAgain orderNumber="TC-300" currentGateway="paystack" country="NG" />);
    fireEvent.click(screen.getByRole("button", { name: /pay now/i }));
    await waitFor(() => screen.getByRole("button", { name: /bank transfer/i }));
    fireEvent.click(screen.getByRole("button", { name: /bank transfer/i }));

    await waitFor(() => expect(stashBankHandoff).toHaveBeenCalledWith("TC-300", { bank_name: "GTBank" }));
    // The instructions live only in that response — the confirmation page reads the
    // stash; refresh() makes the server re-render with bank_transfer as the latest
    // gateway when we were already sitting on that page.
    expect(replace).toHaveBeenCalledWith("/checkout/confirmation/TC-300");
    expect(refresh).toHaveBeenCalled();
  });
});
