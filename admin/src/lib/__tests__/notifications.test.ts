import { describe, it, expect } from "vitest";
import {
  labelFor,
  orphanedRecipients,
  recipientsFor,
  type NotificationEvent,
  type NotificationRecipient,
} from "@/lib/notifications";

function row(over: Partial<NotificationRecipient> = {}): NotificationRecipient {
  return {
    id: 1,
    event: "order.paid",
    user: null,
    email: "a@x.com",
    address: "a@x.com",
    staff_name: "",
    is_external: true,
    ...over,
  };
}

const EVENTS: NotificationEvent[] = [
  { code: "order.paid", label: "New paid order", description: "" },
  { code: "inventory.low_stock", label: "Low stock", description: "" },
];

describe("recipientsFor", () => {
  it("keeps only the rows for that event", () => {
    const rows = [
      row({ id: 1, event: "order.paid", email: "a@x.com", address: "a@x.com" }),
      row({ id: 2, event: "inventory.low_stock", email: "b@x.com", address: "b@x.com" }),
    ];
    expect(recipientsFor(rows, "order.paid").map((r) => r.id)).toEqual([1]);
  });

  it("sorts staff before external addresses", () => {
    // Not cosmetic. An external address — no account, no second factor, receives order
    // contents indefinitely — is the row worth a second look, and insertion order buries
    // it among colleagues.
    const rows = [
      row({ id: 1, email: "zzz@x.com", address: "zzz@x.com", is_external: true }),
      row({
        id: 2,
        user: 5,
        email: "",
        address: "staff@x.com",
        staff_name: "Aisha",
        is_external: false,
      }),
    ];
    expect(recipientsFor(rows, "order.paid").map((r) => r.id)).toEqual([2, 1]);
  });

  it("sorts alphabetically within each group", () => {
    const rows = [
      row({ id: 1, email: "zed@x.com", address: "zed@x.com" }),
      row({ id: 2, email: "ada@x.com", address: "ada@x.com" }),
    ];
    expect(recipientsFor(rows, "order.paid").map((r) => r.id)).toEqual([2, 1]);
  });
});

describe("labelFor", () => {
  it("names an external row by its address", () => {
    expect(labelFor(row({ email: "pack@x.com" }))).toBe("pack@x.com");
  });

  it("prefers a staff member's name", () => {
    expect(
      labelFor(row({ user: 5, is_external: false, staff_name: "Aisha", address: "a@x.com" })),
    ).toBe("Aisha");
  });

  it("still names a deactivated staff row, which has no address left", () => {
    // The row must stay visible and identifiable — a subscription that silently
    // disappears is how somebody concludes they are still subscribed when they are not.
    expect(
      labelFor(row({ user: 5, is_external: false, staff_name: "", email: "", address: "" })),
    ).toBe("Staff #5");
  });
});

describe("orphanedRecipients", () => {
  it("finds rows whose event has left the registry", () => {
    const rows = [
      row({ id: 1, event: "order.paid" }),
      row({ id: 2, event: "order.renamed_away" }),
    ];
    expect(orphanedRecipients(rows, EVENTS).map((r) => r.id)).toEqual([2]);
  });

  it("is empty when every row matches a known event", () => {
    expect(orphanedRecipients([row()], EVENTS)).toEqual([]);
  });
});
