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

  it("still marks Dashboard on /account itself", () => {
    pathname = "/account";
    render(<AccountNav />);

    expect(current()).toEqual(["Dashboard"]);
  });
});
