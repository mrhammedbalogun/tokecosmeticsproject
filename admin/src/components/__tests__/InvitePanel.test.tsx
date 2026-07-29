import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { InviteForm, InviteList } from "@/components/InvitePanel";
import { ROLES, type StaffInvite } from "@/lib/staff";

const INVITE: StaffInvite = {
  id: 7,
  email: "newhire@toke.test",
  role: "Support",
  state: "pending",
  expires_at: "2026-08-01T00:00:00Z",
  invited_by: "owner@toke.test",
  accepted_at: null,
  revoked_at: null,
  created_at: "2026-07-29T00:00:00Z",
};

function inviteFor(overrides: Partial<StaffInvite>): StaffInvite {
  return { ...INVITE, ...overrides };
}

const noop = vi.fn(async () => ({}));

describe("InviteForm", () => {
  it("offers exactly the four roles", () => {
    // Not five, and not a free-text box: the backend validates against `rbac.ROLES` and
    // a fifth option here would be a 400 with a confusing message.
    render(<InviteForm action={noop} />);

    const select = screen.getByLabelText(/role/i);
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual([...ROLES]);
  });

  it("shows the error the action returned", () => {
    render(<InviteForm action={noop} initialState={{ error: "Already staff." }} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Already staff.");
  });

  it("confirms a sent invite", () => {
    render(<InviteForm action={noop} initialState={{ success: "Invite sent to x@toke.test." }} />);

    expect(screen.getByRole("status")).toHaveTextContent("Invite sent to x@toke.test.");
  });
});

describe("InviteList", () => {
  it("lists an outstanding invite with its role and expiry", () => {
    render(<InviteList invites={[INVITE]} revokeAction={noop} />);

    expect(screen.getByText("newhire@toke.test")).toBeInTheDocument();
    expect(screen.getByText(/Support/)).toBeInTheDocument();
    expect(screen.getByText(/2026-08-01/)).toBeInTheDocument();
  });

  it("hides invites that have already been accepted or revoked", () => {
    // An accepted invite is history — the person is on the roster above, which is the
    // better answer to "did they join". A revoked one is a decision already made.
    render(
      <InviteList
        invites={[
          inviteFor({ id: 1, email: "accepted@toke.test", state: "accepted" }),
          inviteFor({ id: 2, email: "revoked@toke.test", state: "revoked" }),
          inviteFor({ id: 3, email: "live@toke.test", state: "pending" }),
        ]}
        revokeAction={noop}
      />,
    );

    expect(screen.getByText("live@toke.test")).toBeInTheDocument();
    expect(screen.queryByText("accepted@toke.test")).not.toBeInTheDocument();
    expect(screen.queryByText("revoked@toke.test")).not.toBeInTheDocument();
  });

  it("names the invitee in each revoke button", () => {
    // Several rows of "Revoke" is unusable with a screen reader, and this control cancels
    // somebody's ability to become an administrator — the wrong one is a real mistake.
    render(
      <InviteList
        invites={[INVITE, inviteFor({ id: 8, email: "second@toke.test" })]}
        revokeAction={noop}
      />,
    );

    expect(screen.getByRole("button", { name: /revoke the invite for newhire@toke.test/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /revoke the invite for second@toke.test/i })).toBeInTheDocument();
  });

  it("carries the invite id in the form the revoke button submits", () => {
    const { container } = render(<InviteList invites={[INVITE]} revokeAction={noop} />);

    const hidden = container.querySelector('input[name="invite_id"]') as HTMLInputElement;
    expect(hidden.value).toBe("7");
  });

  it("says so when nothing is outstanding", () => {
    render(<InviteList invites={[]} revokeAction={noop} />);

    expect(screen.getByText(/no outstanding invites/i)).toBeInTheDocument();
  });
});
