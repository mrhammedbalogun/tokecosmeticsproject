import { describe, expect, it } from "vitest";
import {
  allLocations,
  locationSummary,
  resumeProblem,
  MAX_RESUME_BYTES,
  type Job,
} from "@/lib/careers";

function job(overrides: Partial<Job> = {}): Job {
  return {
    slug: "sales-representative",
    title: "Sales Representative",
    department: "Sales",
    employment_type: "full_time",
    employment_type_label: "Full-Time",
    workplace_type: "on_site",
    workplace_type_label: "On-site",
    country_name: "Nigeria",
    country_code: "NG",
    compensation_text: "Good Pay",
    summary: "",
    description: "",
    requirements: "",
    locations: [],
    status: "open",
    is_accepting: true,
    published_at: null,
    closes_at: null,
    ...overrides,
  };
}

function file(name: string, size: number): File {
  const f = new File(["x"], name);
  Object.defineProperty(f, "size", { value: size });
  return f;
}

describe("locationSummary", () => {
  it("names the country when a role lists no locations", () => {
    expect(locationSummary(job())).toBe("Nigeria");
  });

  it("names both when there are two", () => {
    expect(
      locationSummary(job({ locations: [{ id: 1, label: "Lagos" }, { id: 2, label: "Abuja" }] })),
    ).toBe("Lagos and Abuja");
  });

  it("COLLAPSES THE ELEVEN SALES CITIES INTO ONE LEGIBLE LINE", () => {
    // The whole reason a posting carries many locations. Printed in full, this card's
    // subtitle would be longer than the role description — and the board would read as a
    // templated wall, which is exactly what the WordPress page it replaces looked like.
    const cities = ["Alimosho, Lagos", "Iba LG, Lagos", "Agbara LG, Lagos",
      "Lagos Island, Lagos", "Delta State", "Abuja", "Port Harcourt", "Onitsha",
      "Bayelsa", "Benin", "Enugu"];
    const summary = locationSummary(
      job({ locations: cities.map((label, id) => ({ id, label })) }),
    );
    expect(summary).toBe("Alimosho, Lagos and 10 other locations");
  });
});

describe("allLocations", () => {
  it("orders by how many roles hire there, so the busiest city leads", () => {
    const jobs = [
      job({ slug: "a", locations: [{ id: 1, label: "Lagos" }, { id: 2, label: "Enugu" }] }),
      job({ slug: "b", locations: [{ id: 3, label: "Lagos" }] }),
    ];
    expect(allLocations(jobs)).toEqual(["Lagos", "Enugu"]);
  });

  it("de-duplicates across roles", () => {
    const jobs = [
      job({ slug: "a", locations: [{ id: 1, label: "Lagos" }] }),
      job({ slug: "b", locations: [{ id: 2, label: "Lagos" }] }),
    ];
    expect(allLocations(jobs)).toEqual(["Lagos"]);
  });
});

describe("resumeProblem", () => {
  it("accepts the three document types the backend sniffs for", () => {
    for (const name of ["CV.pdf", "cv.DOC", "Ada Obi.docx"]) {
      expect(resumeProblem(file(name, 1024))).toBeNull();
    }
  });

  it("refuses anything else BEFORE it is uploaded", () => {
    // Courtesy, not the rule: the backend re-checks the real bytes regardless. This just
    // saves somebody a thirty-second upload that was always going to be refused.
    expect(resumeProblem(file("payload.exe", 1024))).toMatch(/PDF, DOC or DOCX/);
  });

  it("refuses an empty file and one over 5MB", () => {
    expect(resumeProblem(file("CV.pdf", 0))).toMatch(/empty/);
    expect(resumeProblem(file("CV.pdf", MAX_RESUME_BYTES + 1))).toMatch(/5MB/);
    expect(resumeProblem(file("CV.pdf", MAX_RESUME_BYTES))).toBeNull();
  });

  it("is not fooled by an extension in the middle of the name", () => {
    expect(resumeProblem(file("cv.pdf.exe", 1024))).toMatch(/PDF, DOC or DOCX/);
  });
});
