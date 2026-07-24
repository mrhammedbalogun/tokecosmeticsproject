import type { Metadata } from "next";
import { CheckoutFlow } from "@/components/checkout/CheckoutFlow";

export const metadata: Metadata = { title: "Checkout", robots: { index: false } };

export default function CheckoutPage() {
  return (
    <section className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="sr-only">Checkout</h1>
      <CheckoutFlow />
    </section>
  );
}
