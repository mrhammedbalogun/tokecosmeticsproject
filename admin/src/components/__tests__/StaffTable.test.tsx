import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StaffTable } from "@/components/StaffTable";
import type { StaffMember } from "@/lib/staff";

const MEMBER: StaffMember = {
  id: 1,
  email: "manager@toke.test",
  name: "Mo Manager",
  roles: ["Manager"],
  is_active: true,
  is_superuser: false,
  totp_confirmed: true,
  last_login: "2026-07-28T08:00:00Z",
  date_joined: "2026-01-04T00:00:00Z",
};

function memberFor(overrides: Partial<StaffMember>): StaffMember {
  return { ...MEMBER, ...overrides };
}

describe("StaffTable", () => {
  it("shows each administrator with their role", () => {
    render(<StaffTable members={[MEMBER]} />);

    expect(screen.getByText("Mo Manager")).toBeInTheDocument();
    expect(screen.getByText("manager@toke.test")).toBeInTheDocument();
    expect(screen.getByText("Manager")).toBeInTheDocument();
  });

  it("flags an account that has not confirmed a second factor", () => {
    // The row an Owner most needs to act on: it can pass the password door and reach
    // nothing, and no other screen surfaces it.
    render(
      <StaffTable members={[memberFor({ totp_confirmed: false, second_factor: null })]} />,
    );

    expect(screen.getByText(/not enrolled/i)).toBeInTheDocument();
  });

  it("names the method each enrolled account uses", () => {
    render(
      <StaffTable
        members={[
          memberFor({ totp_confirmed: true, second_factor: "totp" }),
          memberFor({
            id: 2,
            email: "support@toke.test",
            totp_confirmed: false,
            second_factor: "email",
          }),
        ]}
      />,
    );

    expect(screen.getByText("Authenticator")).toBeInTheDocument();
    expect(screen.getByText("Email codes")).toBeInTheDocument();
  });

  it("calls a superuser with no group a superuser, not 'No role'", () => {
    // "No role" on the account that holds every scope would be the most misleading
    // label on the page.
    render(
      <StaffTable members={[memberFor({ roles: [], is_superuser: true, email: "root@toke.test" })]} />,
    );

    expect(screen.getByText(/superuser \(all scopes\)/i)).toBeInTheDocument();
  });

  it("says 'No role' for an ordinary account with no group, because that one is a gap", () => {
    render(<StaffTable members={[memberFor({ roles: [], is_superuser: false })]} />);

    expect(screen.getByText("No role")).toBeInTheDocument();
  });

  it("marks a deactivated account", () => {
    render(<StaffTable members={[memberFor({ is_active: false })]} />);

    expect(screen.getByText(/deactivated/i)).toBeInTheDocument();
  });

  it("shows both roles when an account holds two", () => {
    // Django permits it and the invite flow does not produce it, so the only way to get
    // here is a hand edit — precisely the case worth rendering accurately.
    render(<StaffTable members={[memberFor({ roles: ["Manager", "Support"] })]} />);

    expect(screen.getByText("Manager, Support")).toBeInTheDocument();
  });

  it("says when an account has never signed in", () => {
    render(<StaffTable members={[memberFor({ last_login: null })]} />);

    const row = screen.getByText("manager@toke.test").closest("tr")!;
    expect(within(row).getByText(/never/i)).toBeInTheDocument();
  });

  // --- removing a staff member ------------------------------------------------------
  //
  // Offered per row when a removeAction is wired (the /staff page is Owner-only via
  // staff.manage, and the API re-checks); never on Owner rows, superusers, or the
  // signed-in account itself. Two clicks, because there is no undo button — the
  // account is deactivated and its sessions killed the moment the action lands.

  it("offers no Remove at all when no action is wired", () => {
    render(<StaffTable members={[MEMBER]} />);

    expect(screen.queryByRole("button", { name: /remove/i })).not.toBeInTheDocument();
  });

  it("asks twice before removing, then calls the action with the member id", async () => {
    const removeAction = vi.fn().mockResolvedValue({});
    render(
      <StaffTable members={[MEMBER]} removeAction={removeAction} selfEmail="owner@toke.test" />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Remove manager@toke.test" }));
    expect(removeAction).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Really remove" }));

    await waitFor(() => expect(removeAction).toHaveBeenCalledWith(1));
  });

  it("offers no Remove for Owners, superusers, or yourself", () => {
    const removeAction = vi.fn();
    render(
      <StaffTable
        members={[
          memberFor({ id: 1, email: "owner@toke.test", roles: ["Owner"] }),
          memberFor({ id: 2, email: "root@toke.test", roles: [], is_superuser: true }),
          memberFor({ id: 3, email: "me@toke.test", roles: ["Manager"] }),
          memberFor({ id: 4, email: "support@toke.test", roles: ["Support"] }),
        ]}
        removeAction={removeAction}
        selfEmail="me@toke.test"
      />,
    );

    expect(screen.queryByRole("button", { name: "Remove owner@toke.test" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove root@toke.test" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove me@toke.test" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove support@toke.test" })).toBeInTheDocument();
  });

  it("shows a refusal against the row it refused", async () => {
    const removeAction = vi.fn().mockResolvedValue({ error: "Only the Owner can remove staff." });
    render(
      <StaffTable members={[MEMBER]} removeAction={removeAction} selfEmail="owner@toke.test" />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Remove manager@toke.test" }));
    fireEvent.click(screen.getByRole("button", { name: "Really remove" }));

    await waitFor(() =>
      expect(screen.getByText("Only the Owner can remove staff.")).toBeInTheDocument(),
    );
    expect(screen.getByText("manager@toke.test")).toBeInTheDocument();
  });

  it("a remove that never reaches the server becomes a message, not a crash", async () => {
    const removeAction = vi.fn().mockRejectedValue(new Error("network down"));
    render(
      <StaffTable members={[MEMBER]} removeAction={removeAction} selfEmail="owner@toke.test" />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Remove manager@toke.test" }));
    fireEvent.click(screen.getByRole("button", { name: "Really remove" }));

    await waitFor(() =>
      expect(screen.getByText(/did not reach the server/i)).toBeInTheDocument(),
    );
  });
});
