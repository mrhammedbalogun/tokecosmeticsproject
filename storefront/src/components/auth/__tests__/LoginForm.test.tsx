import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { LoginForm } from "@/components/auth/LoginForm";

/** useActionState needs an action; these tests only exercise the rendered markup, so a
 * no-op stands in for the real Server Function. */
const noop = vi.fn(async () => ({}));

function renderForm(props: Partial<React.ComponentProps<typeof LoginForm>> = {}) {
  return render(<LoginForm next="/account" action={noop} {...props} />);
}

describe("LoginForm", () => {
  it("labels both fields so they are reachable by name", () => {
    renderForm();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it("uses the autocomplete tokens a password manager expects", () => {
    renderForm();
    expect(screen.getByLabelText(/email/i)).toHaveAttribute("autocomplete", "email");
    expect(screen.getByLabelText(/password/i)).toHaveAttribute("autocomplete", "current-password");
  });

  it("stops mobile keyboards mangling the email field", () => {
    // Without autoCapitalize, mobile Safari capitalises the first letter of the address.
    const email = screen.queryByLabelText(/email/i) ?? (renderForm(), screen.getByLabelText(/email/i));
    expect(email).toHaveAttribute("autocapitalize", "none");
    expect(email).toHaveAttribute("type", "email");
  });

  it("carries `next` in a hidden field", () => {
    const { container } = renderForm({ next: "/account/orders" });
    const hidden = container.querySelector('input[name="next"]');
    expect(hidden).toHaveAttribute("value", "/account/orders");
  });

  it("keeps native validation ON — it is the no-JS story", () => {
    // A `noValidate` form loses required/type=email checking entirely when JS is off,
    // which is the whole reason this is a Server Action.
    const { container } = renderForm();
    expect(container.querySelector("form")).not.toHaveAttribute("novalidate");
    expect(screen.getByLabelText(/email/i)).toBeRequired();
    expect(screen.getByLabelText(/password/i)).toBeRequired();
  });

  it("does NOT disable submit on empty fields — that breaks pre-hydration submits", () => {
    renderForm();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeEnabled();
  });

  it("renders the live region on first paint, before there is any error", () => {
    // A live region inserted at the same moment as its content is often not announced,
    // so the container must already be in the DOM when the error arrives.
    const { container } = renderForm();
    expect(container.querySelector('[aria-live="polite"]')).toBeInTheDocument();
  });

  it("announces an error and links it to the fields", () => {
    renderForm({ initialState: { error: "Email or password is incorrect." } });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Email or password is incorrect.");
    expect(screen.getByLabelText(/password/i)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText(/password/i)).toHaveAttribute(
      "aria-describedby", alert.getAttribute("id"),
    );
  });

  it("prefills the email after a failed attempt", () => {
    renderForm({ initialState: { error: "nope", email: "a@b.com" } });
    expect(screen.getByLabelText(/email/i)).toHaveValue("a@b.com");
  });

  it("marks nothing invalid before the user has tried", () => {
    renderForm();
    expect(screen.getByLabelText(/password/i)).not.toHaveAttribute("aria-invalid", "true");
  });

  it("offers registration, carrying the destination across", () => {
    renderForm({ next: "/account/orders" });
    expect(screen.getByRole("link", { name: /create an account/i })).toHaveAttribute(
      "href", "/register?next=%2Faccount%2Forders",
    );
  });

  it("does not link to password reset yet — that page does not exist until item 7", () => {
    renderForm();
    expect(screen.queryByRole("link", { name: /forgot/i })).not.toBeInTheDocument();
  });
});
