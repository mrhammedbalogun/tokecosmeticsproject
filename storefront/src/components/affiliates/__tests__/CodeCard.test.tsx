import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CodeCard } from "@/components/affiliates/CodeCard";

/** The card carries the page's argument, so what it SAYS in each state is the thing
 *  under test — not that it renders. */
describe("CodeCard", () => {
  it("shows a signed-in referrer their real code and link", () => {
    render(
      <CodeCard
        state="ready"
        code="AMINA7K3P"
        shareUrl="https://next.tokecosmetics.com/?ref=AMINA7K3P"
      />,
    );
    expect(screen.getByText("AMINA7K3P")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /referral link/i })).toHaveValue(
      "https://next.tokecosmetics.com/?ref=AMINA7K3P",
    );
    expect(screen.getByRole("button", { name: /copy link/i })).toBeInTheDocument();
  });

  it("never asks a signed-in customer to create an account", () => {
    // This state exists because `signedIn` comes from a cookie while the code comes from
    // a fetch that can fail on a stale token. Offering "Create an account" to somebody
    // the header is already greeting as signed in is the specific bug this pins.
    render(<CodeCard state="no-code" />);
    expect(screen.queryByRole("link", { name: /create an account/i })).toBeNull();
    expect(screen.getByRole("link", { name: /open my referrals/i })).toHaveAttribute(
      "href",
      "/account/referrals",
    );
  });

  it("offers a signed-out reader the account, and returns them here afterwards", () => {
    render(<CodeCard state="anonymous" />);
    expect(screen.getByRole("link", { name: /create an account/i })).toHaveAttribute(
      "href",
      "/register",
    );
    expect(screen.getByRole("link", { name: /already have one/i })).toHaveAttribute(
      "href",
      "/login?next=/affiliates",
    );
  });

  it("keeps the specimen code out of the accessibility tree", () => {
    // "AMINA••••" is a picture of a code, not a code. A screen reader announcing it
    // would read out a stranger's name as though it were the listener's own.
    const { container } = render(<CodeCard state="anonymous" />);
    const specimen = container.querySelector('[aria-hidden="true"]');
    expect(specimen?.textContent).toContain("AMINA");
  });
});
