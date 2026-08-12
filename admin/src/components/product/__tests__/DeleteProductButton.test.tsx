import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

import { DeleteProductButton } from "@/components/product/DeleteProductButton";

const setup = (onDelete = vi.fn().mockResolvedValue({ ok: true })) => {
  render(<DeleteProductButton slug="glow-serum" name="Glow Serum" onDelete={onDelete} />);
  return onDelete;
};

const open = () => fireEvent.click(screen.getByRole("button", { name: "Delete product…" }));
const confirmButton = () => screen.getByRole("button", { name: /Delete this product/ });

beforeEach(() => replace.mockClear());

describe("DeleteProductButton", () => {
  it("does nothing until the product's exact name is retyped", () => {
    const onDelete = setup();
    open();

    // A near-miss must not arm the button — that is the whole point of retyping.
    fireEvent.change(screen.getByLabelText(/type the product/i), {
      target: { value: "glow serum" },
    });
    expect(confirmButton()).toBeDisabled();
    fireEvent.click(confirmButton());
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("deletes and leaves for the list once the name matches", async () => {
    const onDelete = setup();
    open();

    fireEvent.change(screen.getByLabelText(/type the product/i), {
      target: { value: "Glow Serum" },
    });
    expect(confirmButton()).toBeEnabled();
    fireEvent.click(confirmButton());

    await waitFor(() => expect(onDelete).toHaveBeenCalledWith("glow-serum"));
    // `replace`, not `push`: the editor URL 404s the moment the delete lands.
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/products"));
  });

  it("shows the server's refusal and stays on the page", async () => {
    const onDelete = setup(
      vi.fn().mockResolvedValue({ ok: false, error: "Only the Owner can delete a product." }),
    );
    open();

    fireEvent.change(screen.getByLabelText(/type the product/i), {
      target: { value: "Glow Serum" },
    });
    fireEvent.click(confirmButton());

    await waitFor(() =>
      expect(screen.getByText("Only the Owner can delete a product.")).toBeInTheDocument(),
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("turns a dropped request into a message rather than an unmount", async () => {
    const onDelete = setup(vi.fn().mockRejectedValue(new Error("network")));
    open();

    fireEvent.change(screen.getByLabelText(/type the product/i), {
      target: { value: "Glow Serum" },
    });
    fireEvent.click(confirmButton());

    await waitFor(() =>
      expect(screen.getByText(/did not reach the server/i)).toBeInTheDocument(),
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("can be cancelled without consequence", () => {
    const onDelete = setup();
    open();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByRole("button", { name: "Delete product…" })).toBeInTheDocument();
    expect(onDelete).not.toHaveBeenCalled();
  });
});
