export interface CartLine {
  id: number;
  variant_id: number;
  sku: string;
  name: string;
  variant_name: Record<string, string>;
  quantity: number;
  unit_price: string | null;
  line_total: string | null;
  unavailable: boolean;
}
export interface Cart {
  id: string;
  kind: string;
  status: string;
  country: string;
  currency: string;
  items: CartLine[];
  subtotal: string;
  has_unavailable: boolean;
}
export const EMPTY_CART: Cart = {
  id: "", kind: "standard", status: "active", country: "NG", currency: "NGN",
  items: [], subtotal: "0.00", has_unavailable: false,
};
