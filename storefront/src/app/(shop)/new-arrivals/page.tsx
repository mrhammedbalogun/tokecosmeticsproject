import type { Metadata } from "next";
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { EditListing } from "@/components/plp/EditListing";
import { SHOP_EDITS } from "@/lib/shop-edits";
import { editMetadata } from "@/lib/shop-edit-metadata";

const EDIT = SHOP_EDITS["new-arrivals"];

type Search = Promise<Record<string, string | string[] | undefined>>;

export async function generateMetadata(
  { searchParams }: { searchParams: Search },
): Promise<Metadata> {
  return editMetadata(EDIT, await searchParams);
}

export default async function NewArrivalsPage({ searchParams }: { searchParams: Search }) {
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  return <EditListing edit={EDIT} searchParams={await searchParams} country={country} />;
}
