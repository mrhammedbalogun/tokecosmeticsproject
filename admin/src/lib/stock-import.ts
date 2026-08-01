/**
 * The stock import wizard's rules: which columns Django reads, how to guess them from a
 * real spreadsheet's headers, and how to rewrite a file into the shape the endpoint wants.
 *
 * ── THE MAPPING PRODUCES BYTES, AND THE BYTES ARE WHAT TRAVEL ───────────────────────
 *
 * The wizard normalises the operator's file ONCE and then sends those same bytes to the
 * dry-run and, if they accept it, to the apply. That is what makes the preview honest:
 * Plan-17c ruling 2 already guarantees the backend runs identical logic both times, and
 * this guarantees it runs it over identical input. Re-deriving the CSV for the apply would
 * quietly reintroduce the gap the ruling closes — a preview of one file and an apply of
 * another.
 */
import { toCsv } from "@/lib/csv";

/** Exactly the keys `inventory/csv_io._apply_row` reads. Anything else in the file is
 *  dropped: `reserved` and `available` appear in the EXPORT but are computed, and a column
 *  named `quantity` is the only number this endpoint will ever write. */
export const IMPORT_FIELDS = [
  { key: "sku", label: "SKU", required: true },
  { key: "warehouse", label: "Warehouse name", required: true },
  { key: "quantity", label: "Quantity", required: true },
  { key: "low_stock_threshold", label: "Low-stock threshold", required: false },
] as const;

export type ImportField = (typeof IMPORT_FIELDS)[number]["key"];

/** header -> field, as chosen by the operator. A field may be unmapped (""). */
export type ColumnMap = Record<ImportField, string>;

const CANDIDATES: Record<ImportField, string[]> = {
  sku: ["sku", "skucode", "code", "variantsku", "itemcode"],
  warehouse: ["warehouse", "warehousename", "location", "store", "site"],
  quantity: ["quantity", "qty", "count", "onhand", "stock", "realqty"],
  low_stock_threshold: ["lowstockthreshold", "threshold", "lowstock", "reorderlevel"],
};

const normalise = (header: string) => header.toLowerCase().replace(/[^a-z0-9]/g, "");

/**
 * A first guess at the mapping, so the common case is "check this and continue".
 *
 * Exact-ish match only. A fuzzy guess that silently pointed `quantity` at a column called
 * "reserved" would produce a dry-run report that looked perfectly reasonable and an import
 * that set every count to the wrong number — the operator is asked to confirm, but people
 * confirm what is already filled in.
 */
export function guessColumns(headers: string[]): ColumnMap {
  const map = { sku: "", warehouse: "", quantity: "", low_stock_threshold: "" } as ColumnMap;
  const taken = new Set<string>();

  for (const field of IMPORT_FIELDS) {
    const wanted = CANDIDATES[field.key];
    const hit = headers.find(
      (header) => !taken.has(header) && wanted.includes(normalise(header)),
    );
    if (hit) {
      map[field.key] = hit;
      taken.add(hit);
    }
  }
  return map;
}

/** The required fields still missing a column, for a mapping step that refuses to proceed
 *  rather than uploading a file that will fail on every row. */
export function missingRequired(map: ColumnMap): string[] {
  return IMPORT_FIELDS.filter((f) => f.required && !map[f.key]).map((f) => f.label);
}

/**
 * Rewrite the operator's rows into the endpoint's columns.
 *
 * Rows are kept in file order and none is dropped, so an error the backend reports
 * against "row 4" is the operator's row 4 — renumbering here would make the report point
 * at the wrong line of their spreadsheet.
 */
export function normaliseRows(
  headers: string[],
  rows: string[][],
  map: ColumnMap,
): Record<string, string>[] {
  const indexOf = (header: string) => headers.indexOf(header);
  const columns = IMPORT_FIELDS.filter((f) => map[f.key]).map((f) => ({
    key: f.key,
    index: indexOf(map[f.key]),
  }));

  return rows.map((row) => {
    const record: Record<string, string> = {};
    for (const column of columns) {
      record[column.key] = (row[column.index] ?? "").trim();
    }
    return record;
  });
}

/** The file that is uploaded — for the dry-run and, unchanged, for the apply. */
export function buildImportCsv(
  headers: string[],
  rows: string[][],
  map: ColumnMap,
): string {
  const used = IMPORT_FIELDS.filter((f) => map[f.key]).map((f) => f.key as string);
  return toCsv(used, normaliseRows(headers, rows, map));
}

export interface ImportReport {
  created: number;
  updated: number;
  errors: { row: number; error: string }[];
  dry_run: boolean;
}
