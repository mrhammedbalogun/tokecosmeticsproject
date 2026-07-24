import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { StepShell } from "@/components/checkout/StepShell";

describe("StepShell", () => {
  it("shows the body and no Change button when current", () => {
    render(
      <StepShell step={1} title="Sign in" current complete={false}>
        <p>Body content</p>
      </StepShell>
    );

    expect(screen.getByText("Body content")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /change/i })).toBeNull();
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows the summary and a working Change button when complete and not current", () => {
    const onChange = vi.fn();
    render(
      <StepShell
        step={1}
        title="Sign in"
        current={false}
        complete
        summary="jane@example.com"
        onChange={onChange}
      >
        <p>Body content</p>
      </StepShell>
    );

    expect(screen.getByText("jane@example.com")).toBeInTheDocument();
    expect(screen.queryByText("Body content")).toBeNull();

    const changeBtn = screen.getByRole("button", { name: /change sign in/i });
    expect(changeBtn).toBeInTheDocument();
    fireEvent.click(changeBtn);
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("hides body and summary and shows no Change button when neither current nor complete (locked)", () => {
    render(
      <StepShell
        step={3}
        title="Delivery"
        current={false}
        complete={false}
        summary="should not show"
      >
        <p>Body content</p>
      </StepShell>
    );

    expect(screen.getByText("Delivery")).toBeInTheDocument();
    expect(screen.queryByText("Body content")).toBeNull();
    expect(screen.queryByText("should not show")).toBeNull();
    expect(screen.queryByRole("button", { name: /change/i })).toBeNull();
  });

  it("sets aria-expanded to match the current step", () => {
    const { rerender } = render(
      <StepShell step={1} title="Sign in" current complete={false}>
        <p>Body content</p>
      </StepShell>
    );
    expect(screen.getByRole("region")).toHaveAttribute("aria-expanded", "true");

    rerender(
      <StepShell step={1} title="Sign in" current={false} complete={false}>
        <p>Body content</p>
      </StepShell>
    );
    expect(screen.getByRole("region")).toHaveAttribute("aria-expanded", "false");
  });
});
