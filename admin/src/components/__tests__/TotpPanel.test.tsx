import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TotpPanel } from "@/components/TotpPanel";
import type { ConfirmState, EnrolState, RecoveryState } from "@/app/totp/actions";

const noopEnrol = vi.fn(async (): Promise<EnrolState> => ({}));
const noopConfirm = vi.fn(async (): Promise<ConfirmState> => ({}));
const noopRecovery = vi.fn(async (): Promise<RecoveryState> => ({}));

function panel(props: Partial<React.ComponentProps<typeof TotpPanel>> = {}) {
  return render(
    <TotpPanel
      next="/"
      setup={false}
      recovery={false}
      enrolAction={noopEnrol}
      confirmAction={noopConfirm}
      recoveryAction={noopRecovery}
      {...props}
    />,
  );
}

describe("the TOTP step", () => {
  it("offers a recovery-code route out — the backend path existed; without this it served only people who read the runbook", () => {
    panel();
    const link = screen.getByRole("link", { name: /recovery code/i });
    expect(link).toHaveAttribute("href", "/totp?recovery=1");
  });

  it("asks for a code by default", () => {
    panel();
    expect(screen.getByLabelText(/six-digit code/i)).toBeInTheDocument();
  });

  it("in setup mode asks the staff member to generate a key first", () => {
    panel({ setup: true });
    expect(screen.getByRole("button", { name: /show my setup key/i })).toBeInTheDocument();
  });

  it("in recovery mode swaps the form and drops the six-digit field", () => {
    panel({ recovery: true });
    expect(screen.getByLabelText(/recovery code/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/six-digit code/i)).not.toBeInTheDocument();
  });

  it("carries ?next= through the ceremony so a deep link survives the second factor", () => {
    const { container } = panel({ next: "/orders/42" });
    const hidden = container.querySelector('input[name="next"]') as HTMLInputElement;
    expect(hidden.value).toBe("/orders/42");
  });
});
