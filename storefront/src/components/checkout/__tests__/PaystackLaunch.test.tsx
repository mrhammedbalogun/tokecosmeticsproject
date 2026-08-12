import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";

// Mock the Paystack SDK: constructing it yields an object whose resumeTransaction
// invokes whichever callback the test wants (default = the "customer paid" path).
// The component imports the SDK dynamically inside its effect (module-scope import
// breaks SSR — the SDK touches `window` on evaluation), so every assertion below
// waits: the pop-up opens a microtask after mount, not synchronously.
// NOTE: no vi.restoreAllMocks() here — it wipes the implementations of mocks created
// inside a vi.mock factory, so the second test would get a PaystackPop with no
// resumeTransaction. Nothing in this file is a spy on a real object, so there is
// nothing to restore; mockReset in beforeEach gives each test a clean slate.
const resumeTransaction = vi.fn();
vi.mock("@paystack/inline-js", () => ({
  default: vi.fn().mockImplementation(() => ({ resumeTransaction })),
}));

import { PaystackLaunch } from "@/components/checkout/PaystackLaunch";

interface Callbacks {
  onSuccess: (t: unknown) => void;
  onCancel: () => void;
  onError: (e: unknown) => void;
}

beforeEach(() => {
  // Block body on purpose: mockReset() RETURNS the mock, and vitest treats a function
  // returned from beforeEach as a teardown callback — it would call resumeTransaction()
  // with no arguments after every test.
  resumeTransaction.mockReset();
  resumeTransaction.mockImplementation((_code: string, cbs: Callbacks) => {
    cbs.onSuccess({ id: 1, reference: "TC-ref-1", message: "Approved" });
  });
});

describe("PaystackLaunch", () => {
  it("opens the pop-up with the access code and calls onGatewaySuccess when paid", async () => {
    const onGatewaySuccess = vi.fn();
    const onGatewayAbort = vi.fn();
    render(
      <PaystackLaunch
        data={{ access_code: "ac_123" }}
        onGatewaySuccess={onGatewaySuccess}
        onGatewayAbort={onGatewayAbort}
      />
    );
    await waitFor(() =>
      expect(resumeTransaction).toHaveBeenCalledWith("ac_123", expect.any(Object))
    );
    expect(onGatewaySuccess).toHaveBeenCalled();
    expect(onGatewayAbort).not.toHaveBeenCalled();
  });

  it("calls onGatewayAbort when the customer cancels the pop-up", async () => {
    resumeTransaction.mockImplementation((_code: string, cbs: Callbacks) => {
      cbs.onCancel();
    });
    const onGatewaySuccess = vi.fn();
    const onGatewayAbort = vi.fn();
    render(
      <PaystackLaunch
        data={{ access_code: "ac_123" }}
        onGatewaySuccess={onGatewaySuccess}
        onGatewayAbort={onGatewayAbort}
      />
    );
    await waitFor(() => expect(onGatewayAbort).toHaveBeenCalled());
    expect(onGatewaySuccess).not.toHaveBeenCalled();
  });

  it("calls onGatewayAbort when the transaction fails to load", async () => {
    resumeTransaction.mockImplementation((_code: string, cbs: Callbacks) => {
      cbs.onError({ message: "could not load" });
    });
    const onGatewaySuccess = vi.fn();
    const onGatewayAbort = vi.fn();
    render(
      <PaystackLaunch
        data={{ access_code: "ac_123" }}
        onGatewaySuccess={onGatewaySuccess}
        onGatewayAbort={onGatewayAbort}
      />
    );
    await waitFor(() => expect(onGatewayAbort).toHaveBeenCalled());
    expect(onGatewaySuccess).not.toHaveBeenCalled();
  });

  it("aborts without opening the pop-up when there is no access code", async () => {
    const onGatewaySuccess = vi.fn();
    const onGatewayAbort = vi.fn();
    render(
      <PaystackLaunch
        data={{}}
        onGatewaySuccess={onGatewaySuccess}
        onGatewayAbort={onGatewayAbort}
      />
    );
    await waitFor(() => expect(onGatewayAbort).toHaveBeenCalled());
    expect(resumeTransaction).not.toHaveBeenCalled();
    expect(onGatewaySuccess).not.toHaveBeenCalled();
  });

  it("aborts when the SDK throws instead of opening", async () => {
    resumeTransaction.mockImplementation(() => {
      throw new Error("SDK blew up");
    });
    const onGatewaySuccess = vi.fn();
    const onGatewayAbort = vi.fn();
    render(
      <PaystackLaunch
        data={{ access_code: "ac_123" }}
        onGatewaySuccess={onGatewaySuccess}
        onGatewayAbort={onGatewayAbort}
      />
    );
    await waitFor(() => expect(onGatewayAbort).toHaveBeenCalled());
    expect(onGatewaySuccess).not.toHaveBeenCalled();
  });

  it("opens the pop-up exactly once across re-renders (StrictMode double-invoke)", async () => {
    const onGatewaySuccess = vi.fn();
    const onGatewayAbort = vi.fn();
    const { rerender } = render(
      <PaystackLaunch
        data={{ access_code: "ac_123" }}
        onGatewaySuccess={onGatewaySuccess}
        onGatewayAbort={onGatewayAbort}
      />
    );
    rerender(
      <PaystackLaunch
        data={{ access_code: "ac_123" }}
        onGatewaySuccess={onGatewaySuccess}
        onGatewayAbort={onGatewayAbort}
      />
    );
    await waitFor(() => expect(resumeTransaction).toHaveBeenCalled());
    // Flush any straggler async opens before asserting the count.
    await new Promise((r) => setTimeout(r, 0));
    expect(resumeTransaction).toHaveBeenCalledTimes(1);
  });
});
