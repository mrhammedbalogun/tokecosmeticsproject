import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

let pathname = "/account";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

import { AccountNav } from "@/components/account/AccountNav";

const current = () => screen.getAllByRole("link")
  .filter((a) => a.getAttribute("aria-current") === "page")
  .map((a) => a.textContent);

describe("AccountNav active state", () => {
  it("marks exactly the current section", () => {
    pathname = "/account/profile";
    render(<AccountNav />);

    expect(current()).toEqual(["Profile"]);
  });

  it("keeps Orders highlighted on a nested order detail page", () => {
    pathname = "/account/orders/TC-100038";
    render(<AccountNav />);

    expect(current()).toEqual(["Orders"]);
  });

  it("does not light up Dashboard for every nested route — /account is a prefix of them all", () => {
    pathname = "/account/orders";
    render(<AccountNav />);

    expect(current()).toEqual(["Orders"]);
  });

  it("respects the path boundary — /account/orders-archive is not inside /account/orders", () => {
    // A bare startsWith(href) would highlight Orders here. The separator is the point.
    pathname = "/account/orders-archive";
    render(<AccountNav />);

    expect(current()).toEqual([]);
  });

  it("still marks Dashboard on /account itself", () => {
    pathname = "/account";
    render(<AccountNav />);

    expect(current()).toEqual(["Dashboard"]);
  });

  // Replaces the two pairwise "X immediately after Y" checks that grew one per shipped
  // page. Those pinned insertion POSITION, so adding a link between two of them failed a
  // test that was not about the new link at all (Refer & earn, 2026-08-14). One list is
  // both stricter and easier to update deliberately: the order is stated once, and a
  // reviewer can see what it is meant to be.
  it("lists the sections in the intended order", () => {
    pathname = "/account";
    render(<AccountNav />);

    const labels = screen.getAllByRole("link").map((a) => a.textContent);
    expect(labels).toEqual([
      "Dashboard",
      "Orders",
      // Above the maintenance pages on purpose: it is the one entry a customer might come
      // to the account area specifically to USE, rather than to fix something.
      "Refer & earn",
      "Addresses",
      "Wishlist",
      "Profile",
      "Security",
    ]);
  });

  it("marks Addresses current on /account/addresses", () => {
    pathname = "/account/addresses";
    render(<AccountNav />);

    expect(current()).toEqual(["Addresses"]);
  });

  it("marks Wishlist current on /account/wishlist", () => {
    pathname = "/account/wishlist";
    render(<AccountNav />);

    expect(current()).toEqual(["Wishlist"]);
  });

  it("keeps Refer & earn highlighted on its sub-pages", () => {
    // /account/referrals/payouts and /account/referrals/activity are both inside the
    // section, and the prefix rule has to survive two levels, not just one.
    pathname = "/account/referrals/payouts";
    render(<AccountNav />);

    expect(current()).toEqual(["Refer & earn"]);
  });
});
