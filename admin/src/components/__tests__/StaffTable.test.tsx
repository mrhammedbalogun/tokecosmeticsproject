import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
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
});
