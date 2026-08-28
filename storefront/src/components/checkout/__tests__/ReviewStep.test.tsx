import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useEffect } from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CheckoutProvider, useCheckout } from "@/components/checkout/CheckoutContext";
import { ReviewStep } from "@/components/checkout/ReviewStep";
import { readBankHandoff } from "@/lib/bank-handoff";
import type { Cart } from "@/lib/cart-types";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

/** The launcher owns the inline-SDK collection step; stub it so these tests can assert
 * WHICH launch info ReviewStep hands over without loading gateway SDKs. */
vi.mock("@/components/checkout/PaymentLauncher", () => ({
  PaymentLauncher: ({ launch }: { launch: { gateway: string; reference: string } }) => (
    <div data-testid="launcher">
      {launch.gateway}:{launch.reference}
    </div>
  ),
}));

/** ReviewStep reads cart.id/items/currency/subtotal from useCart() — mock it the
 * same way DeliveryStep.test.tsx does so each test can pin the cart independently. */
let mockCart: Cart;
vi.mock("@/hooks/useCart", () => ({
  useCart: () => ({
    cart: mockCart,
    isLoading: false,
    addItem: { mutate: vi.fn() },
    setQty: { mutate: vi.fn() },
  }),
}));

function makeCart(overrides: Partial<Cart> = {}): Cart {
  return {
    id: "cart-1",
    kind: "standard",
    status: "active",
    country: "GB",
    currency: "GBP",
    items: [
      { id: 1, variant_id: 1, sku: "SKU1", name: "Rose Serum", variant_name: {}, quantity: 2, unit_price: "10.00", line_total: "20.00", unavailable: false },
    ],
    subtotal: "20.00",
    has_unavailable: false,
    ...overrides,
  };
}

/** Harness: seeds selections the way steps 1-4 would have left them (via
 * setSelection, which shallow-merges without touching the step machine — same
 * escape hatch CheckoutContext exposes for exactly this kind of test seeding),
 * then renders the real ReviewStep next to the machine's state for assertions. */
function Harness() {
  const { selections, setSelection } = useCheckout();
  useEffect(() => {
    setSelection({
      addressId: 7,
      addressDisplay: "1 Rose St, London",
      deliveryOptionId: 2,
      deliveryDisplay: "Standard — £5.00",
      paymentGateway: "bank_transfer",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div>
      <p data-testid="note">{selections.note}</p>
      <ReviewStep />
    </div>
  );
}

/** The Plan-38 guest twin of `Harness`: `guest` present is what puts every later step
 *  into guest mode, and the address arrives inline instead of as a saved id. */
function GuestHarness() {
  const { setSelection } = useCheckout();
  useEffect(() => {
    setSelection({
      guest: { email: "guest@example.com", phone: "+2348012345678" },
      guestAddress: {
        first_name: "Ada", last_name: "Obi", phone: "+2348012345678",
        line1: "1 Guest Close", country_code: "NG", state_region: 1,
      },
      addressDisplay: "1 Guest Close",
      deliveryOptionId: 2,
      deliveryDisplay: "Standard — £5.00",
      paymentGateway: "bank_transfer",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <ReviewStep />;
}

function renderHarness(harness: React.ReactNode = <Harness />) {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <CheckoutProvider>
        {harness}
      </CheckoutProvider>
    </QueryClientProvider>
  );
}

type Route = { status: number; body: unknown };

/** Routes fetch calls by exact URL; `routes` maps a URL to a canned Response. Second
 * param is typed (even though unused in the body) so `mock.calls[i][1]` — used below
 * to assert the POST body — type-checks as a 2-tuple. */
function mockFetch(routes: Record<string, Route>) {
  const f = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
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

const QUOTE_URL = "/api/checkout/quote";
const PLACE_URL = "/api/checkout";

const originalFetch = global.fetch;

beforeEach(() => {
  mockCart = makeCart();
  sessionStorage.clear();
  push.mockClear();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("ReviewStep", () => {
  it("quotes on mount and shows the authoritative grand total", async () => {
    mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
  });

  it("places the order with expected_total from the quote and the stashed coupon code, then navigates + stashes bank details", async () => {
    sessionStorage.setItem("toke-coupon-code", "SAVE10");
    const f = mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "2.00", delivery: "5.00", tax: "0.00", grand_total: "23.00", currency: "GBP" }, coupon: { ok: true } },
      },
      [PLACE_URL]: {
        status: 201,
        body: {
          order_number: "TC-100",
          payment: { gateway: "bank_transfer", action: "bank_details", data: { display: { Bank: "GTB", "Account number": "0011" }, reference: "TC-100", instructions: "Use your order number." } },
        },
      },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("£23.00")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /place order/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/checkout/confirmation/TC-100"));

    const placeCall = f.mock.calls.find((c) => c[0] === PLACE_URL)!;
    const body = JSON.parse((placeCall[1] as RequestInit).body as string);
    expect(body).toMatchObject({
      cart_id: "cart-1",
      address_id: 7,
      delivery_option_id: 2,
      payment_gateway: "bank_transfer",
      coupon_code: "SAVE10",
      expected_total: "23.00",
    });
    expect(typeof body.idempotency_key).toBe("string");
    expect(body.idempotency_key.length).toBeGreaterThan(0);

    expect(readBankHandoff("TC-100")).toEqual({
      display: { Bank: "GTB", "Account number": "0011" },
      reference: "TC-100",
      instructions: "Use your order number.",
    });
    expect(sessionStorage.getItem("toke-coupon-code")).toBeNull();
  });

  it("shows a specific message and re-enables the button on a 409 idempotency conflict", async () => {
    mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
      [PLACE_URL]: { status: 409, body: { error: "idempotency_in_progress" } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
    const button = screen.getByRole("button", { name: /place order/i });
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/still finishing your previous attempt/i));
    expect(button).not.toBeDisabled();
    expect(push).not.toHaveBeenCalled();
  });

  it("reuses the SAME idempotency_key on a retry after a lost-response failure — so the backend can replay the original order instead of orphaning it", async () => {
    // Simulates a network blip: the backend already created the order but the
    // response never made it back (a generic fetch rejection). The button
    // re-enables and the shopper clicks Place order again — that retry must carry
    // the identical key so the backend's idempotency layer replays the stored 201.
    const f = mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
      [PLACE_URL]: { status: 409, body: { error: "idempotency_in_progress" } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
    const button = screen.getByRole("button", { name: /place order/i });

    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    fireEvent.click(button);
    await waitFor(() => expect(f.mock.calls.filter((c) => c[0] === PLACE_URL)).toHaveLength(2));

    const placeCalls = f.mock.calls.filter((c) => c[0] === PLACE_URL);
    const firstKey = JSON.parse((placeCalls[0][1] as RequestInit).body as string).idempotency_key;
    const secondKey = JSON.parse((placeCalls[1][1] as RequestInit).body as string).idempotency_key;
    expect(firstKey).toBe(secondKey);
    expect(typeof firstKey).toBe("string");
    expect(firstKey.length).toBeGreaterThan(0);
  });

  it("maps a CheckoutError (insufficient_stock) to a specific message with a cart link, button re-enabled", async () => {
    mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
      [PLACE_URL]: { status: 409, body: { error: "insufficient_stock", detail: "SKU1 has only 1 left." } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
    const button = screen.getByRole("button", { name: /place order/i });
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/no longer available/i));
    expect(screen.getByRole("link", { name: /review your cart/i })).toHaveAttribute("href", "/cart");
    expect(button).not.toBeDisabled();
  });

  it("reads the guest coupon-code stash into the quote request on mount", async () => {
    sessionStorage.setItem("toke-coupon-code", "WELCOME");
    const f = mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "2.00", delivery: "5.00", tax: "0.00", grand_total: "23.00", currency: "GBP" }, coupon: { ok: true } },
      },
    });

    renderHarness();

    await waitFor(() => expect(f).toHaveBeenCalled());
    const [, init] = f.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.coupon_code).toBe("WELCOME");
  });

  it("sends a guest's email AND phone on the quote, so the referral preview tells the truth", async () => {
    // A guest is identified to the referral programme by these two fields and nothing
    // else. Without the phone, the preview cannot tell a self-referring guest apart from
    // any other shopper, so it would quote the 5% and `place_order` would then refuse it
    // — the shopper's reward for clicking pay being a `cart_changed` error. The email was
    // already going for the per-email coupon limits; the phone rides the same request.
    const f = mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
    });

    renderHarness(<GuestHarness />);

    await waitFor(() => expect(f).toHaveBeenCalled());
    const [, init] = f.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.guest_email).toBe("guest@example.com");
    expect(body.guest_phone).toBe("+2348012345678");
    // The inline address goes with them, and no saved-address id — this is the guest twin.
    expect(body.address).toBeTruthy();
    expect(body.address_id).toBeUndefined();
  });

  it("renders PaymentLauncher (not a redirect to confirmation) for an online gateway", async () => {
    mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
      [PLACE_URL]: {
        status: 201,
        body: { order_number: "TC-200", payment: { gateway: "paystack", action: "redirect", reference: "TC-ref-1", data: { access_code: "ac_1" } } },
      },
    });
    renderHarness();
    await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /place order/i }));
    await waitFor(() => expect(screen.getByTestId("launcher")).toHaveTextContent("paystack:TC-ref-1"));
    expect(push).not.toHaveBeenCalled(); // no confirmation redirect for the inline path
  });

  it("does NOT stash a bank handoff for an online gateway", async () => {
    // payment.data for an online gateway holds SDK material (access_code, order_id) --
    // stashing it as a bank handoff would make the confirmation page show bank-transfer
    // instructions for a card order.
    mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
      [PLACE_URL]: {
        status: 201,
        body: { order_number: "TC-201", payment: { gateway: "paystack", action: "redirect", reference: "TC-ref-2", data: { access_code: "ac_2" } } },
      },
    });
    renderHarness();
    await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /place order/i }));
    await waitFor(() => expect(screen.getByTestId("launcher")).toBeInTheDocument());
    expect(readBankHandoff("TC-201")).toBeNull();
  });

  // --- referral code -----------------------------------------------------------------
  // The field also lives on /cart, but "Buy now" and the cart drawer both reach checkout
  // without rendering that page, so for those shoppers this is the only place a code
  // read off a WhatsApp message can be entered.

  it("offers the referral field collapsed, with no input until asked for", async () => {
    // Collapsed on every surface, deliberately: most shoppers have no code, and an open
    // box labelled "referral code" invites people to hunt for one they do not have — at
    // the review step that means leaving a checkout they had almost finished. Reaffirmed
    // by Hammed 2026-08-28 after a build that opened it here; `initiallyOpen` still
    // exists on the component and nothing passes it.
    mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
    });
    renderHarness();
    // Let the mount quote settle before asserting, so the state update it causes lands
    // inside the test rather than after it (React act warning otherwise).
    await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
    expect(
      screen.getByRole("button", { name: /have a friend.s referral code/i }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/friend.s referral code/i)).not.toBeInTheDocument();
  });

  it("applies a referral code and RE-QUOTES, so the customer's discount lands on screen", async () => {
    // This test used to be called "…without re-quoting", and asserted the opposite. That
    // was true until 2026-08-27, when the referred customer's 5% shipped: attribution now
    // moves the total as well as deciding who gets paid, so the totals on screen are
    // stale the instant a code is accepted and `referralNonce` has to re-run the quote.
    // The old assertion survived that change by luck — its `waitFor` settled on the
    // success message, which can land before the re-quote's fetch is recorded, so it was
    // reading the count in a race it usually won. Pinned properly now: the SECOND quote
    // is what the shopper is charged, and the number on screen must be the server's.
    const routes = {
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
      "/api/referral": {
        status: 200,
        body: { valid: true, referrer_name: "Amina", customer_discount_percent: "5.00" },
      },
    };
    const f = mockFetch(routes);
    renderHarness();
    await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
    const quotesBefore = f.mock.calls.filter(([url]) => url === QUOTE_URL).length;

    // The server takes the 5% off the goods on the NEXT quote; mutating the canned route
    // is how this stands in for that (mockFetch reads `routes` per call).
    routes[QUOTE_URL] = {
      status: 200,
      body: { totals: { subtotal: "20.00", discount: "0.00", referral_discount: "1.00", referral_discount_percent: "5.00", delivery: "5.00", tax: "0.00", grand_total: "24.00", currency: "GBP" }, coupon: { ok: true } },
    };

    fireEvent.click(screen.getByRole("button", { name: /have a friend.s referral code/i }));
    const input = screen.getByLabelText(/friend.s referral code/i);
    fireEvent.change(input, { target: { value: "amina7k3p" } });
    // Scoped to the field's own row: the coupon box above has an "Apply" button too, and
    // a page-wide lookup would be ambiguous.
    fireEvent.click(within(input.parentElement as HTMLElement).getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(screen.getByText(/Amina.s link/)).toBeInTheDocument());
    const call = f.mock.calls.find(([url]) => url === "/api/referral");
    // Sent as typed — normalisation and validation are the server's job, and the cookie
    // it sets is the only thing checkout will trust.
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ code: "amina7k3p" });
    // The discount the lookup quoted is named in the confirmation, so the field never
    // promises money off that the checkout will not give.
    expect(screen.getByText(/5% off for you/)).toBeInTheDocument();
    await waitFor(() =>
      expect(f.mock.calls.filter(([url]) => url === QUOTE_URL).length).toBe(quotesBefore + 1),
    );
    await waitFor(() => expect(screen.getByText("£24.00")).toBeInTheDocument());
  });

  it("clears the guest coupon stash on the online-gateway path too", async () => {
    sessionStorage.setItem("toke-coupon-code", "SAVE10");
    mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "2.00", delivery: "5.00", tax: "0.00", grand_total: "23.00", currency: "GBP" }, coupon: { ok: true } },
      },
      [PLACE_URL]: {
        status: 201,
        body: { order_number: "TC-202", payment: { gateway: "paypal", action: "redirect", reference: "TC-ref-3", data: { order_id: "PP-1", currency: "GBP" } } },
      },
    });
    renderHarness();
    await waitFor(() => expect(screen.getByText("£23.00")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /place order/i }));
    await waitFor(() => expect(screen.getByTestId("launcher")).toHaveTextContent("paypal:TC-ref-3"));
    expect(sessionStorage.getItem("toke-coupon-code")).toBeNull();
  });
});
