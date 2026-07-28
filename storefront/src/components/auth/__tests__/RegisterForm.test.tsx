import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { RegisterForm } from "@/components/auth/RegisterForm";

const noop = vi.fn(async () => ({}));

function renderForm(props: Partial<React.ComponentProps<typeof RegisterForm>> = {}) {
  return render(<RegisterForm next="/account" action={noop} {...props} />);
}

describe("RegisterForm", () => {
  it("collects the fields the serializer requires", () => {
    renderForm();
    expect(screen.getByLabelText(/first name/i)).toBeRequired();
    expect(screen.getByLabelText(/^email$/i)).toBeRequired();
    expect(screen.getByLabelText(/^password$/i)).toBeRequired();
  });

  it("leaves last name optional", () => {
    renderForm();
    expect(screen.getByLabelText(/last name/i)).not.toBeRequired();
  });

  it("asks for a NEW password, so managers offer a generated one", () => {
    renderForm();
    expect(screen.getByLabelText(/^password$/i)).toHaveAttribute("autocomplete", "new-password");
  });

  it("leaves marketing consent unticked by default", () => {
    renderForm();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("keeps native validation and an always-enabled submit for the no-JS path", () => {
    const { container } = renderForm();
    expect(container.querySelector("form")).not.toHaveAttribute("novalidate");
    expect(screen.getByRole("button", { name: /create account/i })).toBeEnabled();
  });

  it("has the live region on first paint", () => {
    const { container } = renderForm();
    expect(container.querySelector('[aria-live="polite"]')).toBeInTheDocument();
  });

  it("offers sign-in when the address is already taken, carrying the destination", () => {
    renderForm({
      next: "/account/orders",
      initialState: {
        error: "An account with this email already exists.",
        emailTaken: true,
        next: "/account/orders",
      },
    });

    expect(screen.getByRole("alert")).toHaveTextContent(/already exists/i);
    expect(screen.getByRole("link", { name: /sign in instead/i })).toHaveAttribute(
      "href", "/login?next=%2Faccount%2Forders",
    );
  });

  it("does not offer that shortcut for an ordinary validation error", () => {
    renderForm({ initialState: { error: "This password is too common.", emailTaken: false } });
    expect(screen.queryByRole("link", { name: /sign in instead/i })).not.toBeInTheDocument();
  });

  it("keeps what the user typed after a failure", () => {
    renderForm({
      initialState: { error: "Too short.", email: "a@b.com", firstName: "Ada", lastName: "Lovelace" },
    });
    expect(screen.getByLabelText(/^email$/i)).toHaveValue("a@b.com");
    expect(screen.getByLabelText(/first name/i)).toHaveValue("Ada");
    expect(screen.getByLabelText(/last name/i)).toHaveValue("Lovelace");
  });

  it("always links to sign-in for people who are simply in the wrong place", () => {
    renderForm({ next: "/cart" });
    expect(screen.getByRole("link", { name: /^sign in$/i })).toHaveAttribute(
      "href", "/login?next=%2Fcart",
    );
  });
});
