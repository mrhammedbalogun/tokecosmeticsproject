import type { Metadata } from "next";
import Link from "next/link";
import { NewComboForm } from "@/components/combo/NewComboForm";
import { requireAdmin } from "@/lib/session";
import { createComboAction } from "./actions";

export const metadata: Metadata = { title: "New combo" };

const PATH = "/combos/new";

/**
 * `/combos/new` — two fields and a button.
 *
 * NO DATA IS FETCHED HERE, deliberately. The products, countries and currencies the
 * builder needs are irrelevant to a record that does not exist yet, and loading them
 * would make the emptiest page in the app the slowest.
 */
export default async function NewComboPage() {
  await requireAdmin(PATH);

  return (
    <div>
      <Link href="/combos" className="text-xs text-muted underline-offset-2 hover:underline">
        ← Combos
      </Link>

      <h1 className="mt-2 text-lg font-semibold tracking-tight">New combo</h1>
      <p className="mt-1 text-sm text-muted">
        Just enough to create it. The products, markets and price are on the next screen.
      </p>

      <div className="mt-6">
        <NewComboForm action={createComboAction} />
      </div>
    </div>
  );
}
