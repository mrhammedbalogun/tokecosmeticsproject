import { describe, it, expect } from "vitest";
import { parseCsv, toCsv } from "@/lib/csv";
import {
  buildImportCsv,
  guessColumns,
  missingRequired,
  normaliseRows,
  type ColumnMap,
} from "@/lib/stock-import";

describe("parseCsv", () => {
  it("reads a plain file", () => {
    const { headers, rows } = parseCsv("sku,warehouse,quantity\nA-1,Lagos HQ,40\n");

    expect(headers).toEqual(["sku", "warehouse", "quantity"]);
    expect(rows).toEqual([["A-1", "Lagos HQ", "40"]]);
  });

  it("keeps a comma inside a quoted field", () => {
    const { rows } = parseCsv('sku,warehouse\n"A,1","Lagos, Nigeria"\n');

    expect(rows).toEqual([["A,1", "Lagos, Nigeria"]]);
  });

  it("unescapes a doubled quote", () => {
    const { rows } = parseCsv('sku\n"He said ""hi"""\n');

    expect(rows).toEqual([['He said "hi"']]);
  });

  it("handles a newline inside a quoted field", () => {
    const { rows } = parseCsv('sku,note\nA-1,"line one\nline two"\n');

    expect(rows).toEqual([["A-1", "line one\nline two"]]);
  });

  it("handles CRLF, which is what a spreadsheet exports", () => {
    const { headers, rows } = parseCsv("sku,qty\r\nA-1,5\r\n");

    expect(headers).toEqual(["sku", "qty"]);
    expect(rows).toEqual([["A-1", "5"]]);
  });

  it("STRIPS THE BOM Excel writes", () => {
    // Left in, it becomes part of the first header name and that column matches nothing.
    const { headers } = parseCsv("﻿sku,qty\nA-1,5\n");

    expect(headers[0]).toBe("sku");
  });

  it("reads a final row with no trailing newline", () => {
    expect(parseCsv("sku\nA-1").rows).toEqual([["A-1"]]);
  });

  it("drops blank lines rather than reporting them as rows", () => {
    expect(parseCsv("sku\nA-1\n\n\n").rows).toEqual([["A-1"]]);
  });
});

describe("toCsv", () => {
  it("quotes only what would otherwise change meaning", () => {
    const out = toCsv(["sku", "warehouse"], [{ sku: "A,1", warehouse: "Lagos" }]);

    expect(out).toBe('sku,warehouse\r\n"A,1",Lagos\r\n');
  });

  it("round-trips through the parser", () => {
    const written = toCsv(["sku", "note"], [{ sku: "A-1", note: 'a "quoted", comma' }]);

    expect(parseCsv(written).rows).toEqual([["A-1", 'a "quoted", comma']]);
  });
});

describe("guessColumns", () => {
  it("matches the export's own headers", () => {
    const map = guessColumns(["sku", "warehouse", "quantity", "low_stock_threshold"]);

    expect(map.sku).toBe("sku");
    expect(map.warehouse).toBe("warehouse");
    expect(map.quantity).toBe("quantity");
    expect(map.low_stock_threshold).toBe("low_stock_threshold");
  });

  it("matches the headers a real spreadsheet has", () => {
    const map = guessColumns(["SKU Code", "Warehouse Name", "Qty"]);

    expect(map).toMatchObject({
      sku: "SKU Code",
      warehouse: "Warehouse Name",
      quantity: "Qty",
    });
  });

  it("DOES NOT GUESS FROM A NEAR MISS", () => {
    // Pointing quantity at "reserved" would give a plausible dry-run and an import that
    // set every count to the wrong number. People confirm what is already filled in.
    expect(guessColumns(["sku", "warehouse", "reserved", "available"]).quantity).toBe("");
  });

  it("never assigns one column to two fields", () => {
    const map = guessColumns(["stock"]);
    const used = Object.values(map).filter(Boolean);

    expect(new Set(used).size).toBe(used.length);
  });
});

describe("missingRequired", () => {
  it("names the required fields with no column", () => {
    const map = { sku: "sku", warehouse: "", quantity: "", low_stock_threshold: "" } as ColumnMap;

    expect(missingRequired(map)).toEqual(["Warehouse name", "Quantity"]);
  });

  it("is satisfied without the optional one", () => {
    const map = {
      sku: "a", warehouse: "b", quantity: "c", low_stock_threshold: "",
    } as ColumnMap;

    expect(missingRequired(map)).toEqual([]);
  });
});

describe("normaliseRows and buildImportCsv", () => {
  const headers = ["Qty", "SKU Code", "Warehouse Name"];
  const rows = [
    ["40", "A-1", "Lagos HQ"],
    ["7", "B-2", "UK Warehouse"],
  ];
  const map = {
    sku: "SKU Code",
    warehouse: "Warehouse Name",
    quantity: "Qty",
    low_stock_threshold: "",
  } as ColumnMap;

  it("reorders the operator's columns into the endpoint's", () => {
    expect(normaliseRows(headers, rows, map)).toEqual([
      { sku: "A-1", warehouse: "Lagos HQ", quantity: "40" },
      { sku: "B-2", warehouse: "UK Warehouse", quantity: "7" },
    ]);
  });

  it("KEEPS ROW ORDER AND DROPS NOTHING", () => {
    // The backend reports errors as "row 4". Renumbering here would point the operator
    // at the wrong line of their own spreadsheet.
    const withBlank = [...rows, ["", "", ""]];

    expect(normaliseRows(headers, withBlank, map)).toHaveLength(3);
  });

  it("omits an unmapped optional column entirely", () => {
    expect(buildImportCsv(headers, rows, map)).toBe(
      "sku,warehouse,quantity\r\nA-1,Lagos HQ,40\r\nB-2,UK Warehouse,7\r\n",
    );
  });

  it("includes the optional column when it is mapped", () => {
    const withThreshold = { ...map, low_stock_threshold: "Qty" } as ColumnMap;

    expect(buildImportCsv(headers, [rows[0]], withThreshold)).toBe(
      "sku,warehouse,quantity,low_stock_threshold\r\nA-1,Lagos HQ,40,40\r\n",
    );
  });
});
