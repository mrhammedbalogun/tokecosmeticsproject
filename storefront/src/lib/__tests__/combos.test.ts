import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiFetch, ApiError: class extends Error {} }));

import { getCombo, getCombos } from "@/lib/combos";

/** The `next` options the fetcher handed to `apiFetch`. */
const nextOf = () => (apiFetch.mock.calls[0][1] as {
  next: { revalidate: number; tags: string[] };
}).next;

describe("combo cache configuration", () => {
  // The TTL and the tags are one decision. 300s is only affordable BECAUSE Django
  // flushes all three of these tags on every combo write (`apps/combos/revalidate.py`);
  // drop a tag and the number beside it stops being a backstop and becomes a bug.
  beforeEach(() => { apiFetch.mockReset(); apiFetch.mockResolvedValue([]); });

  it("lists combos for 300s under catalog AND combos", async () => {
    // BOTH: the Combo Deals listing is tagged `combos`, but the homepage's Combo Deals
    // row is a plain catalogue fetch, so a combo edit has to reach `catalog` too.
    await getCombos("NG");
    expect(nextOf()).toEqual({ revalidate: 300, tags: ["catalog", "combos"] });
  });

  it("tags a combo page with catalog, combos AND its own slug", async () => {
    await getCombo("glow-box", "NG");
    expect(nextOf()).toEqual({
      revalidate: 300, tags: ["catalog", "combos", "combo:glow-box"],
    });
  });

  it("keeps the combo tag SPECIFIC to the slug asked for", async () => {
    await getCombo("another-box", "NG");
    expect(nextOf().tags).toContain("combo:another-box");
    expect(nextOf().tags).not.toContain("combo:glow-box");
  });

  it("the tag names match the ones Django sends", async () => {
    // Two halves of one contract in two languages, with nothing but strings between
    // them: apps/combos/revalidate.py::notify_combo_changed emits exactly these three.
    await getCombo("glow-box", "NG");
    expect(nextOf().tags).toEqual(
      expect.arrayContaining(["catalog", "combos", "combo:glow-box"]),
    );
  });
});
