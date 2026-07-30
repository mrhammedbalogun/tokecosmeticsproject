import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { AuditTable } from "@/components/AuditTable";
import type { AuditRow } from "@/lib/audit";

const ROW: AuditRow = {
  id: 1,
  created_at: "2026-07-29T09:15:00Z",
  actor: 4,
  actor_email: "owner@toke.test",
  token_jti: "abc123",
  client_ip: "102.89.1.1",
  model_label: "catalog.product",
  object_id: "77",
  action: "update",
  changes: { price: ["100.00", "120.00"] },
};

function rowFor(overrides: Partial<AuditRow>): AuditRow {
  return { ...ROW, ...overrides };
}

describe("AuditTable", () => {
  it("shows who did what to which record", () => {
    render(<AuditTable rows={[ROW]} />);

    expect(screen.getByText("owner@toke.test")).toBeInTheDocument();
    expect(screen.getByText("update")).toBeInTheDocument();
    expect(screen.getByText("Product #77")).toBeInTheDocument();
  });

  it("lists changed field NAMES in the table and keeps the values hidden", () => {
    // The privacy property, asserted rather than described: `changes` on an order or
    // customer edit holds personal data, and a table renders every row at once.
    render(<AuditTable rows={[ROW]} />);

    expect(screen.getByText("price")).toBeInTheDocument();
    expect(screen.queryByText(/120\.00/)).not.toBeInTheDocument();
  });

  it("reveals the values only when a row is expanded", () => {
    render(<AuditTable rows={[ROW]} />);

    fireEvent.click(screen.getByRole("button", { name: /show the recorded values/i }));

    expect(screen.getByText(/120\.00/)).toBeInTheDocument();
  });

  it("keeps the actor's address for a row whose account has been deleted", () => {
    // `actor` goes NULL when the account is deleted; `actor_email` is the SNAPSHOT and
    // is the whole reason the column exists. A table that read the FK would blank out
    // precisely the rows belonging to somebody who has left.
    render(<AuditTable rows={[rowFor({ actor: null, actor_email: "gone@toke.test" })]} />);

    expect(screen.getByText("gone@toke.test")).toBeInTheDocument();
  });

  it("says plainly when there is nothing to show", () => {
    render(<AuditTable rows={[]} />);

    expect(screen.getByText(/no audit entries match/i)).toBeInTheDocument();
  });

  it("renders no expander for a row that recorded no changes", () => {
    // A disclosure control that opens an empty box is worse than no control: it invites
    // a click that answers nothing, on every read-audited row in the log.
    render(<AuditTable rows={[rowFor({ changes: {} })]} />);

    expect(screen.queryByRole("button", { name: /show the recorded values/i })).not.toBeInTheDocument();
  });

  it("gives each row's expander an accessible name that names the record", () => {
    // Two rows, both "Show values", is unusable with a screen reader — and this table is
    // all rows. The name has to carry the record.
    render(<AuditTable rows={[ROW, rowFor({ id: 2, object_id: "88" })]} />);

    const table = screen.getByRole("table");
    expect(within(table).getByRole("button", { name: /Product #77/ })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: /Product #88/ })).toBeInTheDocument();
  });
});
