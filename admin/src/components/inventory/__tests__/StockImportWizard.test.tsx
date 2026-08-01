import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StockImportWizard } from "@/components/inventory/StockImportWizard";

/** Every upload the wizard makes: [url, the CSV text it sent]. */
const sent: Array<{ url: string; body: string }> = [];

function mockUpload(report: unknown, ok = true) {
  global.fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const form = init?.body as FormData;
    const file = form.get("file") as Blob;
    sent.push({ url, body: await file.text() });
    return {
      ok,
      json: async () => report,
    } as unknown as Response;
  }) as unknown as typeof fetch;
}

/** A file with a spreadsheet's headers rather than the endpoint's. */
function chooseFile(text: string, name = "counts.csv") {
  const input = screen.getByLabelText(/choose a csv/i);
  const file = new File([text], name, { type: "text/csv" });
  // jsdom will not let `files` be assigned, so it is defined onto the element.
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

const CSV = "SKU Code,Warehouse Name,Qty\r\nA-1,Lagos HQ,40\r\nB-2,Lagos HQ,7\r\n";
const CLEAN_REPORT = { created: 1, updated: 1, errors: [], dry_run: true };

beforeEach(() => {
  sent.length = 0;
});

describe("StockImportWizard", () => {
  it("guesses the mapping from a real spreadsheet's headers", async () => {
    mockUpload(CLEAN_REPORT);
    render(<StockImportWizard />);

    chooseFile(CSV);

    expect(await screen.findByText(/counts\.csv/)).toBeInTheDocument();
    expect(screen.getByText(/2 rows/)).toBeInTheDocument();
    expect((screen.getByLabelText(/^SKU$/) as HTMLSelectElement).value).toBe("SKU Code");
    expect((screen.getByLabelText(/quantity/i) as HTMLSelectElement).value).toBe("Qty");
  });

  it("CANNOT CHECK A FILE THAT IS MISSING A REQUIRED COLUMN", async () => {
    mockUpload(CLEAN_REPORT);
    render(<StockImportWizard />);
    chooseFile("SKU Code,Reserved\r\nA-1,3\r\n");

    await screen.findByText(/still needed/i);

    expect(screen.getByRole("button", { name: /check this file/i })).toBeDisabled();
    expect(sent).toHaveLength(0);
  });

  it("sends the DRY RUN first, and writes nothing", async () => {
    mockUpload(CLEAN_REPORT);
    render(<StockImportWizard />);
    chooseFile(CSV);
    await screen.findByText(/counts\.csv/);

    fireEvent.click(screen.getByRole("button", { name: /check this file/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].url).toContain("dry_run=1");
    // Rewritten into the endpoint's column names, in file order.
    expect(sent[0].body).toBe(
      "sku,warehouse,quantity\r\nA-1,Lagos HQ,40\r\nB-2,Lagos HQ,7\r\n",
    );
    expect(await screen.findByText("Nothing has been saved yet")).toBeInTheDocument();
  });

  it("APPLIES EXACTLY THE BYTES IT PREVIEWED", async () => {
    // The other half of ruling 2: the backend runs identical logic both times, and this
    // makes sure it runs it over identical input.
    mockUpload(CLEAN_REPORT);
    render(<StockImportWizard />);
    chooseFile(CSV);
    await screen.findByText(/counts\.csv/);
    fireEvent.click(screen.getByRole("button", { name: /check this file/i }));
    await screen.findByText("Nothing has been saved yet");

    fireEvent.click(screen.getByRole("button", { name: /apply 2 rows/i }));

    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].body).toBe(sent[0].body);
    expect(sent[1].url).not.toContain("dry_run");
    expect(await screen.findByText("Imported")).toBeInTheDocument();
  });

  it("reports skipped rows against the line number in their spreadsheet", async () => {
    mockUpload({
      created: 1,
      updated: 0,
      errors: [{ row: 2, error: "unknown sku 'B-2'" }],
      dry_run: true,
    });
    render(<StockImportWizard />);
    chooseFile(CSV);
    await screen.findByText(/counts\.csv/);
    fireEvent.click(screen.getByRole("button", { name: /check this file/i }));

    // Backend row 2 is the operator's line 3, because their file has a header.
    expect(await screen.findByText(/Line 3: unknown sku/)).toBeInTheDocument();
    // The counts sit in their own <strong> elements, so the assertion is on the panel.
    const panel = screen.getByText("Nothing has been saved yet").parentElement;
    expect(panel?.textContent).toMatch(/1\s*skipped/);
  });

  it("offers no apply when every row failed", async () => {
    mockUpload({
      created: 0,
      updated: 0,
      errors: [{ row: 1, error: "unknown warehouse" }],
      dry_run: true,
    });
    render(<StockImportWizard />);
    chooseFile(CSV);
    await screen.findByText(/counts\.csv/);
    fireEvent.click(screen.getByRole("button", { name: /check this file/i }));

    expect(await screen.findByRole("button", { name: /apply 0 rows/i })).toBeDisabled();
  });

  it("refuses a file with no rows", async () => {
    mockUpload(CLEAN_REPORT);
    render(<StockImportWizard />);

    chooseFile("sku,warehouse,quantity\r\n");

    expect(await screen.findByRole("alert")).toHaveTextContent("no rows to import");
    expect(sent).toHaveLength(0);
  });
});
