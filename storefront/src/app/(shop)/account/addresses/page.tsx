import type { Metadata } from "next";
import type { Address } from "@/components/checkout/address-fields";
import { fetchWithAuthOrBounce } from "@/lib/session";
import { AddressBook } from "@/components/account/AddressBook";

export const metadata: Metadata = { title: "Addresses" };

export default async function AddressesPage() {
  // This fetch is the page's gate; `/account/addresses` is the literal current path so
  // an expired session bounces back HERE after renewal, not to the dashboard — same
  // pattern as the profile and orders pages.
  const addresses = await fetchWithAuthOrBounce<Address[]>(
    "/me/addresses/", "/account/addresses",
  );

  return (
    <div>
      <h2 className="font-display text-2xl">Addresses</h2>
      <div className="mt-6">
        <AddressBook initial={addresses} />
      </div>
    </div>
  );
}
