import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

describe("the enrolment screen", () => {
  const SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";
  const URI = `otpauth://totp/Toke%20Cosmetics%20Admin:a@b.com?secret=${SECRET}&issuer=Toke%20Cosmetics%20Admin`;

  /** Drives the real `useActionState` path: click "Show my setup key", resolve the action
   *  with an enrolment, and wait for the re-render. */
  async function enrolled() {
    const enrolAction = vi.fn(
      async (): Promise<EnrolState> => ({
        enrolment: { secret: SECRET, provisioning_uri: URI, issuer: "Toke Cosmetics Admin" },
      }),
    );
    const view = panel({ setup: true, enrolAction });
    fireEvent.click(screen.getByRole("button", { name: /show my setup key/i }));
    await waitFor(() => expect(screen.getByRole("img")).toBeInTheDocument());
    return view;
  }

  it("renders a QR code built locally from the provisioning URI", async () => {
    const { container } = await enrolled();

    const svg = container.querySelector("svg[role='img']");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("aria-label", expect.stringMatching(/qr code/i));
    // A real encoded matrix, not an empty placeholder: a version-5 code with the 4-module
    // quiet zone is ~47 wide, and it must have actual dark runs drawn.
    const [, , width] = (svg!.getAttribute("viewBox") ?? "").split(" ").map(Number);
    expect(width).toBeGreaterThanOrEqual(29);
    expect(svg!.querySelectorAll("rect").length).toBeGreaterThan(20);
  });

  it("never puts the secret anywhere a screen reader would read it aloud", async () => {
    const { container } = await enrolled();
    const label = container.querySelector("svg[role='img']")!.getAttribute("aria-label")!;
    expect(label).not.toContain(SECRET);
  });

  it("reaches no network to do it — the QR is computed in-process", async () => {
    const fetchSpy = vi.fn();
    const original = global.fetch;
    global.fetch = fetchSpy as unknown as typeof fetch;
    try {
      const { container } = await enrolled();
      // No QR web service, no <img> pointing off-origin: the secret never leaves the page.
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(container.querySelector("img")).toBeNull();
    } finally {
      global.fetch = original;
    }
  });

  it("KEEPS the manual fallback alongside the QR — a refactor must not drop it", async () => {
    // The QR is useless on a desktop-only setup, on a phone with camera permission denied,
    // and to a screen-reader user; runbook §6 assumes throughout that a human can type the
    // key instead. This assertion is the thing standing between that and a silent tidy-up.
    const { container } = await enrolled();

    // The grouped base32 key, exactly as an authenticator app prints it.
    const grouped = (SECRET.match(/.{1,4}/g) ?? []).join(" ");
    expect(screen.getByText(grouped)).toBeInTheDocument();

    // And the raw otpauth:// URI, for paste-into-app.
    const details = container.querySelector("details")!;
    expect(within(details).getByText(URI)).toBeInTheDocument();

    // Both still present WITH the QR, not instead of it.
    expect(container.querySelector("svg[role='img']")).toBeInTheDocument();
  });
});
