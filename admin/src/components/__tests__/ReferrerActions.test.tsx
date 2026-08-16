import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReferrerActions } from "@/components/referrals/ReferrerActions";
import type { ReferrerRow } from "@/lib/referrals";

/** `fireEvent`, not `user-event` — this app does not carry that dependency. */
const click = (el: HTMLElement) => fireEvent.click(el);
const type = (el: HTMLElement, value: string) =>
  fireEvent.change(el, { target: { value } });

function referrer(overrides: Partial<ReferrerRow> = {}): ReferrerRow {
  return {
    id: 7,
    email: "amina@example.com",
    toke_id: "TK-000123",
    name: "Amina Okoro",
    code: "AMINA7K3P",
    is_blocked: false,
    blocked_reason: "",
    joined: "2026-01-01T00:00:00Z",
    referred_customers: 4,
    balances: [{ currency: "NGN", available: "30000.00", pending: "0.00", lifetime: "30000.00" }],
    ...overrides,
  };
}

function setup(props: Partial<Parameters<typeof ReferrerActions>[0]> = {}) {
  const onBlock = vi.fn().mockResolvedValue({ savedAt: 1 });
  const onAdjust = vi.fn().mockResolvedValue({ savedAt: 1 });
  render(
    <ReferrerActions
      referrer={referrer()}
      canManage
      onBlock={onBlock}
      onAdjust={onAdjust}
      {...props}
    />,
  );
  return { onBlock, onAdjust };
}

describe("ReferrerActions", () => {
  it("says so plainly when the viewer may look but not act", () => {
    setup({ canManage: false });
    expect(screen.getByText(/read-only/i)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("will not block without a reason", async () => {
    // "Why is this person blocked" gets asked months later, by somebody else.
    const { onBlock } = setup();
    click(screen.getByRole("button", { name: /^block$/i }));
    expect(screen.getByRole("button", { name: /confirm block/i })).toBeDisabled();

    type(screen.getByLabelText(/why are you blocking/i), "Six orders to their own address.");
    click(screen.getByRole("button", { name: /confirm block/i }));

    await waitFor(() =>
      expect(onBlock).toHaveBeenCalledWith({
        id: 7, blocked: true, reason: "Six orders to their own address.",
      }),
    );
  });

  it("unblocks in one click and asks for nothing", async () => {
    // Unblocking restores the default; requiring a justification to stop punishing
    // somebody is friction pointed the wrong way.
    const { onBlock } = setup({ referrer: referrer({ is_blocked: true }) });
    click(screen.getByRole("button", { name: /unblock/i }));
    await waitFor(() =>
      expect(onBlock).toHaveBeenCalledWith({ id: 7, blocked: false, reason: "" }),
    );
  });

  it("tells you in words which direction the money is about to move", async () => {
    // THE POINT OF THE PREVIEW. A leading "-" is one glyph; "Takes ... OFF" is a
    // sentence, and the failure it guards against — crediting what you meant to claw
    // back — is invisible until somebody reconciles the month.
    setup();
    click(screen.getByRole("button", { name: /adjust balance/i }));

    type(screen.getByLabelText(/amount/i), "-2500");
    expect(screen.getByText(/Takes NGN 2,500.00 OFF/)).toBeInTheDocument();

    type(screen.getByLabelText(/amount/i), "2500");
    expect(screen.getByText(/Adds NGN 2,500.00 TO/)).toBeInTheDocument();
  });

  it("will not write an adjustment without both an amount and a reason", async () => {
    const { onAdjust } = setup();
    click(screen.getByRole("button", { name: /adjust balance/i }));
    const submit = screen.getByRole("button", { name: /write adjustment/i });
    expect(submit).toBeDisabled();

    type(screen.getByLabelText(/amount/i), "-2500.00");
    expect(submit).toBeDisabled();

    type(screen.getByLabelText(/^reason$/i), "Refund landed after the payout went.");
    click(submit);

    await waitFor(() =>
      expect(onAdjust).toHaveBeenCalledWith({
        id: 7,
        currency: "NGN",
        amount: "-2500.00",
        kind: "correction",
        reason: "Refund landed after the payout went.",
      }),
    );
  });

  it("surfaces the server's refusal rather than inventing one", async () => {
    const onAdjust = vi.fn().mockResolvedValue({
      message: "The shop does not pay out GBP, so a GBP balance could never be withdrawn.",
    });
    render(
      <ReferrerActions
        referrer={referrer()}
        canManage
        onBlock={vi.fn()}
        onAdjust={onAdjust}
      />,
    );
    click(screen.getByRole("button", { name: /adjust balance/i }));
    type(screen.getByLabelText(/amount/i), "50");
    type(screen.getByLabelText(/^reason$/i), "Retainer");
    click(screen.getByRole("button", { name: /write adjustment/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("does not pay out GBP");
  });
});
