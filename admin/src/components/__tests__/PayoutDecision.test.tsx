import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PayoutDecision } from "@/components/referrals/PayoutDecision";
import type { PayoutRow } from "@/lib/referrals";

/** `fireEvent`, not `user-event`: this app does not carry that dependency (see
 *  GlobalSearch.test.tsx, which says the same). Every interaction here is a click or a
 *  change on a controlled field, which fireEvent models exactly. */
const click = (el: HTMLElement) => fireEvent.click(el);
const type = (el: HTMLElement, value: string) =>
  fireEvent.change(el, { target: { value } });


function row(overrides: Partial<PayoutRow> = {}): PayoutRow {
  return {
    id: 42,
    created_at: "2026-08-01T09:00:00Z",
    status: "requested",
    currency: "NGN",
    amount: "30000.00",
    // Zero by ruling — the card hides the split unless a deduction was actually taken.
    wht_rate_percent: "0.00",
    wht_amount: "0.00",
    net_amount: "30000.00",
    referrer_id: 7,
    referrer_name: "Amina Okoro",
    referrer_email: "amina@example.com",
    referrer_toke_id: "TK-000123",
    referrer_is_blocked: false,
    bank_name: "GTBank",
    account_name: "AMINA OKORO",
    account_number: "0123456789",
    bank_code: "058",
    commission_count: 3,
    flags: [],
    days_open: 2,
    decided_at: null,
    decided_by_email: "",
    paid_at: null,
    reference: "",
    admin_note: "",
    customer_message: "",
    ...overrides,
  };
}

function setup(props: Partial<Parameters<typeof PayoutDecision>[0]> = {}) {
  const onApprove = vi.fn().mockResolvedValue({ savedAt: 1 });
  const onReject = vi.fn().mockResolvedValue({ savedAt: 1 });
  const onMarkPaid = vi.fn().mockResolvedValue({ savedAt: 1 });
  render(
    <PayoutDecision
      row={row()}
      canDecide
      canPay
      onApprove={onApprove}
      onReject={onReject}
      onMarkPaid={onMarkPaid}
      {...props}
    />,
  );
  return { onApprove, onReject, onMarkPaid };
}

describe("PayoutDecision", () => {
  it("offers nothing on a payout that is already settled", () => {
    // `paid` and `rejected` are terminal. Money has moved, or the commissions are already
    // back in the referrer's balance; a live button on either is a way to make a mess.
    setup({ row: row({ status: "paid" }) });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("says so plainly when the viewer may look but not decide", () => {
    // Support holds referrals.view to answer "where is my commission?". Rendering dead
    // buttons for them would be a 403 waiting to happen.
    setup({ canDecide: false, canPay: false });
    expect(screen.getByText(/read-only/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });

  it("hides Mark paid from a role that lacks referrals.pay but keeps Approve", () => {
    setup({ canPay: false });
    expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mark paid/i })).not.toBeInTheDocument();
  });

  it("will not mark a payout paid without the bank's reference", async () => {
    // The reference is the only artefact that answers "I never received it" months later.
    const { onMarkPaid } = setup();

    click(screen.getByRole("button", { name: /mark paid/i }));
    expect(screen.getByRole("button", { name: /confirm paid/i })).toBeDisabled();

    type(screen.getByLabelText(/bank transfer reference/i), "GTB/2026/0042");
    click(screen.getByRole("button", { name: /confirm paid/i }));

    await waitFor(() =>
      expect(onMarkPaid).toHaveBeenCalledWith({
        id: 42, reference: "GTB/2026/0042", adminNote: "",
      }),
    );
  });

  it("will not reject without a sentence the customer will read", async () => {
    // A refusal with no reason is a support ticket every single time, and the reviewer is
    // the only person who knows why.
    const { onReject } = setup();

    click(screen.getByRole("button", { name: /^reject$/i }));
    expect(screen.getByRole("button", { name: /confirm reject/i })).toBeDisabled();

    type(screen.getByLabelText(/what the customer will see/i), "The account name does not match.");
    click(screen.getByRole("button", { name: /confirm reject/i }));

    await waitFor(() =>
      expect(onReject).toHaveBeenCalledWith({
        id: 42,
        customerMessage: "The account name does not match.",
        adminNote: "",
      }),
    );
  });

  it("approves in one click — the reversible action asks for nothing", async () => {
    const { onApprove } = setup();
    click(screen.getByRole("button", { name: /approve/i }));
    await waitFor(() => expect(onApprove).toHaveBeenCalledWith({ id: 42, adminNote: "" }));
  });

  it("shows the server's own sentence when somebody else decided the row first", async () => {
    // The 409 two people working the queue at month end will actually produce. The
    // service knows whether it was already paid or already rejected; inventing a vaguer
    // message here would be worse than the one it sent.
    const onApprove = vi
      .fn()
      .mockResolvedValue({ message: "That request is no longer open." });
    render(
      <PayoutDecision
        row={row()}
        canDecide
        canPay
        onApprove={onApprove}
        onReject={vi.fn()}
        onMarkPaid={vi.fn()}
      />,
    );

    click(screen.getByRole("button", { name: /approve/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("no longer open");
  });

  it("does not offer Approve on a row that is already approved, but still offers paying it", () => {
    // The gap between "we will send this" and "it left" is days long and real.
    setup({ row: row({ status: "approved" }) });
    expect(screen.queryByRole("button", { name: /^approve$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /mark paid/i })).toBeInTheDocument();
    // And rejectable, for a transfer the bank bounced.
    expect(screen.getByRole("button", { name: /^reject$/i })).toBeInTheDocument();
  });
});
