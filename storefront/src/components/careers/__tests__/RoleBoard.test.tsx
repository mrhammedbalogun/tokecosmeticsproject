import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { RoleBoard } from "@/components/careers/RoleBoard";
import type { Job } from "@/lib/careers";

function job(overrides: Partial<Job> = {}): Job {
  return {
    slug: "role", title: "Sales Representative", department: "Sales",
    employment_type: "full_time", employment_type_label: "Full-Time",
    workplace_type: "on_site", workplace_type_label: "On-site",
    country_name: "Nigeria", country_code: "NG", compensation_text: "Good Pay",
    summary: "", description: "", requirements: "", locations: [],
    status: "open", is_accepting: true, published_at: null, closes_at: null,
    ...overrides,
  };
}

describe("the role board", () => {
  it("links each card to its own page, with the TITLE as the link name", () => {
    // Not the whole card: a link wrapping a heading and three badges reads as one
    // enormous run-on link, and its accessible name becomes the card's entire text.
    render(<RoleBoard jobs={[job({ slug: "ops", title: "Operations Manager" })]} />);
    const link = screen.getByRole("link", { name: "Operations Manager" });
    expect(link.getAttribute("href")).toBe("/careers/ops");
  });

  it("offers no filter when every role is in one place", () => {
    render(<RoleBoard jobs={[job({ locations: [{ id: 1, label: "Lagos" }] })]} />);
    expect(screen.queryByRole("group", { name: /Filter roles/ })).toBeNull();
  });

  it("filters to the chosen city, and back", () => {
    const jobs = [
      job({ slug: "sales", title: "Sales Representative",
            locations: [{ id: 1, label: "Enugu" }, { id: 2, label: "Lagos" }] }),
      job({ slug: "ops", title: "Operations Manager",
            locations: [{ id: 3, label: "Lagos" }] }),
    ];
    render(<RoleBoard jobs={jobs} />);

    fireEvent.click(screen.getByRole("button", { name: "Enugu" }));
    expect(screen.queryByRole("link", { name: "Operations Manager" })).toBeNull();
    expect(screen.getByRole("link", { name: "Sales Representative" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "All locations" }));
    expect(screen.getByRole("link", { name: "Operations Manager" })).toBeTruthy();
  });

  it("offers a way out of an empty filter rather than a dead end", () => {
    // Reachable because the filter offers every city on the board, not every city per
    // role: pick Enugu while the only Enugu role has just closed and this is the state.
    const jobs = [
      job({ slug: "lagos-role", locations: [{ id: 1, label: "Lagos" }] }),
      job({ slug: "enugu-role", title: "Ops", locations: [{ id: 2, label: "Enugu" }] }),
    ];
    const { rerender } = render(<RoleBoard jobs={jobs} />);
    fireEvent.click(screen.getByRole("button", { name: "Enugu" }));
    // The Enugu role goes; the chip stays selected because the reader selected it.
    rerender(<RoleBoard jobs={[jobs[0]]} />);

    expect(screen.getByText(/Nothing open in Enugu right now/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "See every open role" }));
    expect(screen.getByRole("link", { name: "Sales Representative" })).toBeTruthy();
  });

  it("summarises many locations instead of listing them", () => {
    const cities = ["Alimosho, Lagos", "Abuja", "Enugu", "Benin"];
    render(<RoleBoard jobs={[job({ locations: cities.map((label, id) => ({ id, label })) })]} />);
    expect(screen.getByText("Alimosho, Lagos and 3 other locations")).toBeTruthy();
  });

  it("marks a closed role and still links to it", () => {
    render(<RoleBoard jobs={[job({ is_accepting: false, status: "closed" })]} />);
    expect(screen.getByText("Closed")).toBeTruthy();
    expect(screen.getByText("Read the role")).toBeTruthy();
  });
});
