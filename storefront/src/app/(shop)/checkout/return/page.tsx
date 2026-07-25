import type { Metadata } from "next";
import { CheckoutReturn } from "@/components/checkout/CheckoutReturn";

type SearchParams = Promise<{ [key: string]: string | string[] | undefined }>;

export const metadata: Metadata = { title: "Confirming your payment", robots: { index: false } };

/** Where a redirect gateway (Flutterwave) sends the customer back to. `ref` is the
 * gateway reference the SERVER baked into the return URL at initiate time — it is only
 * a lookup key here; the verify endpoint scopes it to the requesting user's own orders,
 * so a tampered value cannot reach anyone else's payment. */
export default async function CheckoutReturnPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const ref = typeof params.ref === "string" ? params.ref : "";

  return (
    <div className="mx-auto max-w-md px-4 py-16 text-center">
      <CheckoutReturn reference={ref} />
    </div>
  );
}
