import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CardAddButton } from "@/components/product/CardAddButton";
import { EMPTY_CART } from "@/lib/cart-types";

const push = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh }) }));

function mockAddResponse(make: () => Response) {
  const f = vi.fn((url: string | URL, init?: RequestInit) => {
    if (String(url) === "/api/cart/items" && init?.method === "POST") {
      return Promise.resolve(make());
    }
    return Promise.resolve(new Response(JSON.stringify(EMPTY_CART), { status: 200 }));
  });
  global.fetch = f as unknown as typeof fetch;
  return f;
}

const originalFetch = global.fetch;

function renderButton() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CardAddButton variantId={7} name="Glow Serum" slug="glow-serum" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  push.mockClear();
  refresh.mockClear();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("CardAddButton", () => {
  it("409 out_of_stock swaps the button for Just Sold Out in place — no navigation", async () => {
    mockAddResponse(
      () =>
        new Response(
          JSON.stringify({ detail: "This item just sold out.", code: "out_of_stock" }),
          { status: 409 },
        ),
    );
    renderButton();

    fireEvent.click(screen.getByRole("button", { name: "Add Glow Serum to cart" }));

    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
    expect(screen.getByText("Just Sold Out")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(push).not.toHaveBeenCalled();
    expect(refresh).toHaveBeenCalled();
  });

  it("any other add failure still falls back to the PDP", async () => {
    mockAddResponse(() => new Response(JSON.stringify({ detail: "boom" }), { status: 500 }));
    renderButton();

    fireEvent.click(screen.getByRole("button", { name: "Add Glow Serum to cart" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/product/glow-serum"));
    expect(screen.queryByText("Just Sold Out")).toBeNull();
  });
});
