import { describe, it, expect, vi } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { ComboRow, rowTitle } from "@/components/home/ComboRow";
import {
  comboGift,
  comboSavingPercent,
  promoCombos,
  rewardClaim,
  type ComboCard as ComboCardData,
} from "@/lib/combos";

vi.mock("@/components/motion/Motion", () => ({
  FadeUp: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

function make(slug: string, over: Partial<ComboCardData> = {}): ComboCardData {
  return {
    name: `Combo ${slug}`,
    slug,
    short_description: "Two favourites, one box",
    image: "/media/c.png",
    is_featured: false,
    pricing: {
      amount: "9000.00",
      components_total: "10000.00",
      saving: "1000.00",
      saving_percent: "10.00",
      currency: "NGN",
    },
    item_count: 2,
    item_images: ["/media/a.png", "/media/b.png"],
    in_stock: true,
    ...over,
  };
}

/** A gift bundle: full price for the contents, a gift in the parcel. */
function gift(slug: string, name = "Free Kids Hair Grow Cream"): ComboCardData {
  return make(slug, {
    reward_type: "gift",
    gift: { name, image: null },
    pricing: {
      amount: "10000.00",
      components_total: "10000.00",
      saving: "0.00",
      saving_percent: "0.00",
      currency: "NGN",
    },
  });
}

describe("ComboRow", () => {
  it("renders nothing when there are no combos", () => {
    const { container } = render(<ComboRow combos={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the discount when every combo agrees on it, and links to /combo", () => {
    render(<ComboRow combos={[make("a"), make("b")]} />);
    expect(
      screen.getByRole("heading", { name: "Save 10% when you buy the set" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view all/i })).toHaveAttribute("href", "/combo");
    expect(screen.getByRole("heading", { name: "Combo a" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Combo b" })).toBeInTheDocument();
  });

  it("claims 'up to' the best rate when the combos discount differently", () => {
    const fifteen = make("b", {
      pricing: {
        amount: "8500.00",
        components_total: "10000.00",
        saving: "1500.00",
        saving_percent: "15.00",
        currency: "NGN",
      },
    });
    render(<ComboRow combos={[make("a"), fifteen]} />);
    expect(
      screen.getByRole("heading", { name: "Save up to 15% when you buy the set" }),
    ).toBeInTheDocument();
  });

  it("carries a gift combo, which saves nothing and is still a reward", () => {
    render(<ComboRow combos={[gift("a")]} />);
    expect(
      screen.getByRole("heading", { name: "Every set comes with a free gift" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Free Kids Hair Grow Cream")).toBeInTheDocument();
    // The one thing a gift bundle must NOT show: it charges what the parts cost, so
    // there is no saving to claim and nothing to cross out.
    expect(screen.queryByText(/% off/)).toBeNull();
    expect(screen.queryByText(/Save ₦/)).toBeNull();
  });

  it("sells both rewards when the row holds both", () => {
    render(<ComboRow combos={[make("a"), gift("b")]} />);
    expect(
      screen.getByRole("heading", { name: "Save 10% or get a free gift" }),
    ).toBeInTheDocument();
  });

  it("renders nothing when no combo qualifies for the row", () => {
    const unpriced = make("a", { pricing: null });
    const noSaving = make("b", {
      pricing: {
        amount: "10000.00",
        components_total: "10000.00",
        saving: "0.00",
        saving_percent: "0.00",
        currency: "NGN",
      },
    });
    const { container } = render(<ComboRow combos={[unpriced, noSaving]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("promoCombos", () => {
  it("drops unpriced and no-saving combos and caps the row", () => {
    const dropped = [
      make("unpriced", { pricing: null }),
      make("free-lunch", {
        pricing: {
          amount: "10000.00",
          components_total: "10000.00",
          saving: "0.00",
          saving_percent: "0.00",
          currency: "NGN",
        },
      }),
    ];
    expect(promoCombos([make("a"), ...dropped, make("b")]).map((c) => c.slug)).toEqual(["a", "b"]);
    expect(promoCombos([make("a"), make("b"), make("c")], 2)).toHaveLength(2);
  });

  it("keeps sold-out combos but sorts them last, holding curator order otherwise", () => {
    const row = [make("sold", { in_stock: false }), make("a"), make("b")];
    expect(promoCombos(row).map((c) => c.slug)).toEqual(["a", "b", "sold"]);
  });

  it("does not reorder the array it is given", () => {
    const row = [make("sold", { in_stock: false }), make("a")];
    promoCombos(row);
    expect(row.map((c) => c.slug)).toEqual(["sold", "a"]);
  });

  it("keeps a combo whose payload predates in_stock", () => {
    const old = make("a");
    delete (old as Partial<ComboCardData>).in_stock;
    expect(promoCombos([old])).toHaveLength(1);
  });

  it("trusts a quantized 0.00 rather than recomputing a fraction of a percent", () => {
    // ₦1 off ₦100,000 serialises as "0.00" (the API quantizes to 2dp). Recomputing it
    // from the amounts would put "Save ₦1 · 0% off" on the homepage.
    const crumb = make("a", {
      pricing: {
        amount: "99999.00",
        components_total: "100000.00",
        saving: "1.00",
        saving_percent: "0.00",
        currency: "NGN",
      },
    });
    expect(comboSavingPercent(crumb.pricing)).toBe(0);
    expect(promoCombos([crumb])).toHaveLength(0);
  });

  it("falls back to the two amounts when saving_percent is absent", () => {
    // The one payload shape that has no usable field: cached by an API build from
    // before `saving_percent` existed. An empty or garbage string lands here too; a
    // legitimate "0.00" does NOT, which is the whole point of the test above.
    const old = make("a");
    delete (old.pricing as Partial<NonNullable<ComboCardData["pricing"]>>).saving_percent;
    expect(comboSavingPercent(old.pricing)).toBeCloseTo(10);
    expect(promoCombos([old])).toHaveLength(1);
  });
});

describe("rewardClaim and rowTitle", () => {
  it("claims nothing for an empty row", () => {
    expect(rewardClaim([])).toEqual({ discount: null, gift: false });
    expect(rowTitle([])).toBe("Buy the set, keep the change");
  });

  it("words every combination of rewards", () => {
    expect(rowTitle([make("a")])).toBe("Save 10% when you buy the set");
    expect(rowTitle([gift("a")])).toBe("Every set comes with a free gift");
    expect(rowTitle([make("a"), gift("b")])).toBe("Save 10% or get a free gift");
  });

  it("states a single rate exactly, however untidy", () => {
    const nearly = make("a", {
      pricing: {
        amount: "9049.00",
        components_total: "10000.00",
        saving: "951.00",
        saving_percent: "9.51",
        currency: "NGN",
      },
    });
    expect(rewardClaim([nearly]).discount).toEqual({ percent: 9.51, upTo: false });
  });

  it("floors a mixed claim rather than rounding it past a card's own badge", () => {
    const priced = (slug: string, amount: string, saving: string, percent: string) =>
      make(slug, {
        pricing: {
          amount,
          components_total: "10000.00",
          saving,
          saving_percent: percent,
          currency: "NGN",
        },
      });
    // Rounding 9.51 up would head the row "10%" over a card badged "9.51% off".
    expect(
      rewardClaim([
        priced("a", "9049.00", "951.00", "9.51"),
        priced("b", "9200.00", "800.00", "8.00"),
      ]).discount,
    ).toEqual({ percent: 9, upTo: true });
    // "Up to" takes the BEST rate in the row, not the worst.
    expect(
      rewardClaim([make("a"), priced("b", "9200.00", "800.00", "8.00")]).discount,
    ).toEqual({ percent: 10, upTo: true });
  });
});


describe("comboGift", () => {
  it("is null for a discount combo, and for a payload that predates the choice", () => {
    expect(comboGift(make("a"))).toBeNull();
    // A backend older than this build sends no reward at all; everything that existed
    // then gave a discount.
    const old = make("b");
    delete (old as Partial<ComboCardData>).reward_type;
    expect(comboGift(old)).toBeNull();
  });

  it("names an unnamed gift rather than rendering an empty badge", () => {
    // The database forbids this (`combo_gift_reward_needs_a_gift`), so it should never
    // arrive — but the alternative to a fallback is a live card printing "".
    expect(comboGift({ reward_type: "gift", gift: { name: "   ", image: null } })).toEqual({
      name: "Free gift included",
      image: null,
    });
    expect(comboGift({ reward_type: "gift" })).toEqual({
      name: "Free gift included",
      image: null,
    });
  });

  it("keeps the photograph when there is one", () => {
    expect(comboGift({ reward_type: "gift", gift: { name: "Free soap", image: "/g.png" } }))
      .toEqual({ name: "Free soap", image: "/g.png" });
  });
});
