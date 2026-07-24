import type { Metadata } from "next";
import { CartView } from "@/components/checkout/CartView";

export const metadata: Metadata = { title: "Your bag", robots: { index: false } };

export default function CartPage() {
  return (
    <section className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="font-display text-3xl">Your bag</h1>
      <CartView />
    </section>
  );
}
