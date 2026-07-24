import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CheckoutProvider, useCheckout } from "@/components/checkout/CheckoutContext";
import { SignInStep } from "@/components/checkout/SignInStep";
import { BUYNOW_INTENT_KEY } from "@/lib/buynow-intent";
import type { Cart } from "@/lib/cart-types";
import { EMPTY_CART } from "@/lib/cart-types";

// SignInStep now reads useCart() to snapshot the guest cart id before auth (for
// the cart-merge fix). Mock the hook directly — same pattern as CartView.test.tsx
// — so each test controls `cart.id` without needing a real /api/cart fetch mock.
let mockCart: Cart;
vi.mock("@/hooks/useCart", () => ({
  useCart: () => ({ cart: mockCart }),
}));

/** Small harness exposing the checkout machine's completed/selections state next
 * to the real SignInStep, mirroring the pattern in CheckoutContext.test.tsx —
 * lets assertions target the step machine's outcome rather than SignInStep's
 * internal state (which is meaningless once StepShell would normally unmount it). */
function Harness() {
  const { completed, selections } = useCheckout();
  return (
    <div>
      <p data-testid="completed">{[...completed].sort().join(",")}</p>
      <p data-testid="userEmail">{selections.userEmail ?? ""}</p>
      <SignInStep />
    </div>
  );
}

function renderHarness() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <CheckoutProvider>
        <Harness />
      </CheckoutProvider>
    </QueryClientProvider>
  );
}

type Route = { status: number; body: unknown };

/** Routes fetch calls by exact URL; `routes` maps a URL to a canned Response. */
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
  sessionStorage.clear();
  mockCart = EMPTY_CART;
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("SignInStep", () => {
  it("auto-completes step 1 when already signed in (me check), without merging any cart", async () => {
    // Even if a cart happens to be present, the me-check branch has no "guest"
    // cart to speak of (the shopper is already authenticated) — it must never
    // call /api/cart/merge.
    mockCart = { ...EMPTY_CART, id: "some-cart-id" };
    const f = mockFetch({
      "/api/auth/me": { status: 200, body: { email: "jane@example.com", first_name: "Jane" } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("1"));
    expect(screen.getByTestId("userEmail")).toHaveTextContent("jane@example.com");
    // The form never renders for an already-authenticated shopper.
    expect(screen.queryByLabelText(/^email$/i)).toBeNull();
    expect(f).not.toHaveBeenCalledWith("/api/cart/merge", expect.anything());
  });

  it("registers a new email and completes the step", async () => {
    const f = mockFetch({
      "/api/auth/me": { status: 401, body: { detail: "Not authenticated." } },
      "/api/auth/register": { status: 201, body: { ok: true } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Jane" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "Str0ngPassw0rd!" } });
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("1"));
    expect(screen.getByTestId("userEmail")).toHaveTextContent("new@example.com");
    expect(f).toHaveBeenCalledWith(
      "/api/auth/register",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ email: "new@example.com", password: "Str0ngPassw0rd!", first_name: "Jane" }),
      })
    );
  });

  it("merges the guest cart into the account after registering (checkout-breaking bug fix)", async () => {
    // Reproduces the live bug: a guest with a non-empty cart signs up inline at
    // checkout. Without merging the pre-auth cart id into the new account, the
    // shopper lands on a fresh empty user cart and can't place an order.
    mockCart = { ...EMPTY_CART, id: "guest-cart-77" };
    const f = mockFetch({
      "/api/auth/me": { status: 401, body: { detail: "Not authenticated." } },
      "/api/auth/register": { status: 201, body: { ok: true } },
      "/api/cart/merge": { status: 200, body: { id: "user-cart-1" } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "shopper@example.com" } });
    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Jane" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "Str0ngPassw0rd!" } });
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("1"));
    expect(f).toHaveBeenCalledWith(
      "/api/cart/merge",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ cart_id: "guest-cart-77" }),
      })
    );
  });

  it("does not attempt a merge when the guest cart is empty (no id yet)", async () => {
    mockCart = EMPTY_CART; // id: ""
    const f = mockFetch({
      "/api/auth/me": { status: 401, body: { detail: "Not authenticated." } },
      "/api/auth/register": { status: 201, body: { ok: true } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Jane" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "Str0ngPassw0rd!" } });
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("1"));
    expect(f).not.toHaveBeenCalledWith("/api/cart/merge", expect.anything());
  });

  it("flips to the password/login form when the email already has an account", async () => {
    mockFetch({
      "/api/auth/me": { status: 401, body: { detail: "Not authenticated." } },
      "/api/auth/register": { status: 400, body: { email: ["Account already exists"] } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "dup@example.com" } });
    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Jane" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "Str0ngPassw0rd!" } });
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() =>
      expect(screen.getByText(/already has an account/i)).toBeInTheDocument()
    );
    expect(screen.getByLabelText(/^email$/i)).toHaveValue("dup@example.com");
    expect(screen.getByLabelText(/^email$/i)).toHaveAttribute("readonly");
    expect(screen.queryByLabelText(/first name/i)).toBeNull();

    // And logging in from the flipped form completes the step.
    // (separately verified below with its own fetch mock)
  });

  it("logs in after the existing-email flip, merges the guest cart, and completes the step", async () => {
    mockCart = { ...EMPTY_CART, id: "guest-cart-42" };
    const f = mockFetch({
      "/api/auth/me": { status: 401, body: { detail: "Not authenticated." } },
      "/api/auth/register": { status: 400, body: { email: ["Account already exists"] } },
      "/api/auth/login": { status: 200, body: { ok: true } },
      "/api/cart/merge": { status: 200, body: { id: "user-cart-1" } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "dup@example.com" } });
    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Jane" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "wrongfirsttry" } });
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => expect(screen.getByText(/already has an account/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "correct-password" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("1"));
    expect(screen.getByTestId("userEmail")).toHaveTextContent("dup@example.com");
    expect(f).toHaveBeenCalledWith(
      "/api/cart/merge",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ cart_id: "guest-cart-42" }),
      })
    );
  });

  it("resumes a stashed Buy-Now intent after registering and clears it", async () => {
    sessionStorage.setItem(BUYNOW_INTENT_KEY, JSON.stringify({ variant_id: 5, quantity: 2 }));
    const f = mockFetch({
      "/api/auth/me": { status: 401, body: { detail: "Not authenticated." } },
      "/api/auth/register": { status: 201, body: { ok: true } },
      "/api/checkout/buy-now": { status: 200, body: { id: "cart-1" } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "buyer@example.com" } });
    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Bea" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "Str0ngPassw0rd!" } });
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("1"));
    expect(f).toHaveBeenCalledWith(
      "/api/checkout/buy-now",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ variant_id: 5, quantity: 2 }),
      })
    );
    expect(sessionStorage.getItem(BUYNOW_INTENT_KEY)).toBeNull();
  });

  it("shows a field error and does not complete on a weak-password rejection", async () => {
    mockFetch({
      "/api/auth/me": { status: 401, body: { detail: "Not authenticated." } },
      "/api/auth/register": { status: 400, body: { password: ["This password is too common."] } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Jane" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "password" } });
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() =>
      expect(screen.getByText(/too common/i)).toBeInTheDocument()
    );
    expect(screen.getByTestId("completed")).toHaveTextContent("");
  });
});
