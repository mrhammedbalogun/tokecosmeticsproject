/**
 * A small RFC 4180 CSV reader and writer, for the stock import wizard.
 *
 * WHY NOT A LIBRARY: this parses a file somebody exported from a spreadsheet, in the
 * browser, to show them a column mapping. The whole surface is quotes, escaped quotes and
 * line endings, which is a page of code and a dozen tests — cheaper to own than a
 * dependency in a bundle that ships to an admin over Nigerian mobile data.
 *
 * WHY IT EXISTS AT ALL: Django reads fixed column names (`sku`, `warehouse`, `quantity`,
 * `low_stock_threshold`). Real files say "SKU", "Warehouse Name", "Qty". The wizard maps
 * the operator's headers onto those, and rewrites the file before sending it — so the
 * bytes the backend dry-runs are the bytes it later applies.
 */

/** Parse CSV text into a header row and data rows. Handles quoted fields containing
 *  commas, newlines and doubled quotes, and both LF and CRLF line endings. */
export function parseCsv(text: string): { headers: string[]; rows: string[][] } {
  // A BOM survives Excel exports and would otherwise become part of the first header
  // name, so the first column silently fails to match anything.
  const source = text.replace(/^﻿/, "");
  const rows: string[][] = [];
  let field = "";
  let row: string[] = [];
  let quoted = false;

  for (let i = 0; i < source.length; i++) {
    const char = source[i];

    if (quoted) {
      if (char === '"') {
        if (source[i + 1] === '"') {
          field += '"'; // an escaped quote
          i++;
        } else {
          quoted = false;
        }
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      // Swallow the LF of a CRLF pair rather than emitting an empty row for it.
      if (char === "\r" && source[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      field = "";
      row = [];
    } else {
      field += char;
    }
  }

  // A file that does not end in a newline still has a final row.
  if (field !== "" || row.length) {
    row.push(field);
    rows.push(row);
  }

  const nonEmpty = rows.filter((r) => r.some((cell) => cell.trim() !== ""));
  const [headers = [], ...data] = nonEmpty;
  return { headers: headers.map((h) => h.trim()), rows: data };
}

/** Quote a field only where it would otherwise change meaning. */
function quote(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

/** Serialise rows of records under the given headers. CRLF, which is what RFC 4180 says
 *  and what Excel produces. */
export function toCsv(headers: string[], rows: Record<string, string>[]): string {
  const lines = [headers.map(quote).join(",")];
  for (const record of rows) {
    lines.push(headers.map((header) => quote(record[header] ?? "")).join(","));
  }
  return lines.join("\r\n") + "\r\n";
}
