export interface CartLine {
  id: number;
  variant_id: number;
  sku: string;
  name: string;
  variant_name: Record<string, string>;
  quantity: number;
  /** Absolute URL of the line's picture (thumbnail-first), null when the product
   * has no image. Older cached payloads predate the field — treat as optional. */
  image?: string | null;
  product_slug?: string;
  unit_price: string | null;
  line_total: string | null;
  unavailable: boolean;
}
/**
 * A bundle in the bag: the box, what is in it, and what it saves.
 *
 * ITS COMPONENTS ARE NESTED HERE, NOT IN `Cart.items` — the two lists are disjoint, so
 * rendering both never doubles a line. The nested rows carry their FULL prices; the
 * saving is stated once, as `saving`, exactly as it reaches the order.
 */
export interface CartCombo {
  /** Address for PATCH/DELETE — `/api/cart/combos/{group_id}`. */
  group_id: number;
  combo_slug: string;
  name: string;
  image?: string | null;
  /** How many of the bundle. The component quantities are derived from it. */
  quantity: number;
  items: CartLine[];
  /** Per bundle. `line_total` is this times `quantity`. */
  unit_price: string | null;
  line_total: string | null;
  /** What the same contents cost separately, for the strike-through. */
  components_total: string | null;
  saving: string | null;
  saving_percent?: string;
  /** The DEAL has ended — archived, or withdrawn from this market. The goods are still
   *  in the bag at their own prices and will still be charged; only the discount stops.
   *  Optional: payloads cached from before the field existed carry none. */
  ended?: boolean;
  /** A COMPONENT cannot be priced here at all — the state that really does mean "this
   *  cannot be bought". Distinct from `ended`, which is only about the discount. */
  unavailable: boolean;
}

export interface Cart {
  id: string;
  kind: string;
  status: string;
  country: string;
  currency: string;
  items: CartLine[];
  /** Older cached payloads predate combos — treat as optional and default to []. */
  combos?: CartCombo[];
  /** Every line at its LIST price, combo components included. */
  subtotal: string;
  /** What the bundles take off `subtotal`. "0.00" when there are none. */
  combo_discount?: string;
  /** `subtotal - combo_discount` — what the goods actually cost. */
  total?: string;
  has_unavailable: boolean;
}
export const EMPTY_CART: Cart = {
  id: "", kind: "standard", status: "active", country: "NG", currency: "NGN",
  items: [], combos: [], subtotal: "0.00", combo_discount: "0.00", total: "0.00",
  has_unavailable: false,
};
