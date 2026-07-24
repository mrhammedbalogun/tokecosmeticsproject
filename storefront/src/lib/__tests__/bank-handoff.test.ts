import { describe, it, expect, beforeEach } from "vitest";
import { stashBankHandoff, readBankHandoff, BANK_HANDOFF_KEY } from "@/lib/bank-handoff";

const data = { display: { Bank: "GTB", "Account number": "0123456789" }, reference: "TC-1", instructions: "Use your order number." };
describe("bank-handoff", () => {
  beforeEach(() => sessionStorage.clear());
  it("stashes and reads back by order number", () => {
    stashBankHandoff("TC-1", data);
    expect(readBankHandoff("TC-1")).toEqual(data);
  });
  it("returns null for a different order number", () => {
    stashBankHandoff("TC-1", data);
    expect(readBankHandoff("TC-2")).toBeNull();
  });
  it("returns null when absent and on corrupt JSON", () => {
    expect(readBankHandoff("TC-1")).toBeNull();
    sessionStorage.setItem(BANK_HANDOFF_KEY, "{not json");
    expect(readBankHandoff("TC-1")).toBeNull();
  });
});
