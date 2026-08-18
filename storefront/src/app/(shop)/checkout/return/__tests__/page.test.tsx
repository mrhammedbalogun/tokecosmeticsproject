import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// The page only picks the reference out of the query string; the polling component is
// exercised by its own test, so stub it down to something we can read the prop off.
vi.mock("@/components/checkout/CheckoutReturn", () => ({
  CheckoutReturn: ({ reference }: { reference: string }) => (
    <span data-testid="ref">{reference || "(none)"}</span>
  ),
}));

import CheckoutReturnPage from "../page";

async function renderWith(params: Record<string, string | string[] | undefined>) {
  render(await CheckoutReturnPage({ searchParams: Promise.resolve(params) }));
  return screen.getByTestId("ref").textContent;
}

describe("checkout return page", () => {
  it("uses our own ?ref= on the normal redirect path", async () => {
    expect(await renderWith({ ref: "TC-100007" })).toBe("TC-100007");
  });

  // Paystack appends these itself when it falls back to the dashboard's Live Callback
  // URL, which carries no ?ref= of ours. Reading only `ref` there told a customer who
  // had just paid that we couldn't find their payment.
  it("falls back to Paystack's ?reference=", async () => {
    expect(await renderWith({ reference: "TC-100008" })).toBe("TC-100008");
  });

  it("falls back to Paystack's ?trxref=", async () => {
    expect(await renderWith({ trxref: "TC-100009" })).toBe("TC-100009");
  });

  it("prefers our ref when Paystack appends its own alongside it", async () => {
    expect(await renderWith({ ref: "TC-100010-P4", reference: "TC-100010-P4", trxref: "x" }))
      .toBe("TC-100010-P4");
  });

  it("renders the not-found state when the URL carries no reference at all", async () => {
    expect(await renderWith({})).toBe("(none)");
  });

  it("ignores a repeated param that arrives as an array", async () => {
    expect(await renderWith({ ref: ["a", "b"], reference: "TC-100011" })).toBe("TC-100011");
  });
});
