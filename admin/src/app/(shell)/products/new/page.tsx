import type { Metadata } from "next";
import Link from "next/link";
import { NewProductForm } from "@/components/product/NewProductForm";
import { requireAdmin } from "@/lib/session";
import { createProductAction } from "./actions";

export const metadata: Metadata = { title: "New product" };

const PATH = "/products/new";

/**
 * `/products/new` — two fields and a button.
 *
 * NO DATA IS FETCHED HERE, deliberately. The categories, tags, countries and currencies
 * the editor needs are irrelevant to a record that does not exist yet, and loading them
 * would make the emptiest page in the app the slowest.
 *
 * `requireAdmin` establishes a session and nothing more; whether this person may create a
 * product is decided by `HasAdminScope("products.manage")` on the endpoint, on every
 * request, from the database. A staff member without it gets the form and then the
 * backend's refusal, rendered as a sentence.
 */
export default async function NewProductPage() {
  await requireAdmin(PATH);

  return (
    <div>
      <Link href="/products" className="text-xs text-muted underline-offset-2 hover:underline">
        ← Products
      </Link>

      <h1 className="mt-2 text-lg font-semibold tracking-tight">New product</h1>
      <p className="mt-1 text-sm text-muted">
        Just enough to create it. The rest is on the editor.
      </p>

      <div className="mt-6">
        <NewProductForm action={createProductAction} />
      </div>
    </div>
  );
}
