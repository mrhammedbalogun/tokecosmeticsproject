import type { Metadata } from "next";
import { CheckoutReturn } from "@/components/checkout/CheckoutReturn";

type SearchParams = Promise<{ [key: string]: string | string[] | undefined }>;

export const metadata: Metadata = { title: "Confirming your payment", robots: { index: false } };

/** Where a redirect gateway (Flutterwave, Paystack) sends the customer back to.
 *
 * THREE PARAMETER NAMES, ONE MEANING. `ref` is ours — the gateway reference the SERVER
 * baked into the return URL at initiate time, and the only one present on the normal
 * path. `reference` and `trxref` are Paystack's: it appends them itself when it falls
 * back to the dashboard's "Live Callback URL" (which carries no query string of ours),
 * and reading only `ref` there would tell a customer who HAD just paid that we couldn't
 * find their payment. All three are lookup keys only — the verify endpoint scopes the
 * reference to the requesting user's own orders, so a tampered value reaches nobody
 * else's payment.
 */
export default async function CheckoutReturnPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const first = (...keys: string[]) => {
    for (const key of keys) {
      const value = params[key];
      if (typeof value === "string" && value) return value;
    }
    return "";
  };

  return (
    <div className="mx-auto max-w-md px-4 py-16 text-center">
      <CheckoutReturn reference={first("ref", "reference", "trxref")} />
    </div>
  );
}
