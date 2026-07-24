/** Static per-country delivery lines (Plan-13 D5). The delivery-options endpoint
 * needs an authed user + a cart with lines, so a live PDP quote is impossible until
 * Plan-14 checkout. Hammed owns this copy — edit freely. RoW quotes after payment
 * is the Plan-14a flow; the ZZ line must NOT promise a price. */
const ESTIMATES: Record<string, string> = {
  NG: "Delivery in Nigeria: 1–3 days, from ₦1,500",
  GB: "Delivery to the UK: 5–10 business days, calculated at checkout",
  US: "Delivery to the US: 5–10 business days, calculated at checkout",
  CA: "Delivery to Canada: 5–10 business days, calculated at checkout",
};
const INTERNATIONAL = "International delivery: quoted after checkout";

export function deliveryEstimateFor(countryCode: string): string {
  return ESTIMATES[countryCode] ?? INTERNATIONAL;
}
