import type { Metadata } from "next";
import Link from "next/link";
import { StockImportWizard } from "@/components/inventory/StockImportWizard";
import { requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Import stock" };

const PATH = "/inventory/import";

/**
 * `/inventory/import` — upload a stock CSV, behind `products.manage`.
 *
 * The page itself fetches nothing: the wizard holds the file in the browser and posts it
 * to the BFF, which is the only way the same bytes can be previewed and then applied. See
 * `StockImportWizard` for why that matters.
 */
export default async function StockImportPage() {
  await requireAdmin(PATH);

  return (
    <div>
      <div>
        <Link href="/inventory" className="text-sm text-muted hover:text-foreground">
          ← Inventory
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">Import stock</h1>
        <p className="mt-1 text-sm text-muted">
          Set counts from a spreadsheet. You will see exactly what the file would do before
          anything is saved.
        </p>
      </div>

      <div className="mt-6 max-w-2xl">
        <StockImportWizard />
      </div>
    </div>
  );
}
