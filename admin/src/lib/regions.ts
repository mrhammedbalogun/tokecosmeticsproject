/** The region tree and coverage arithmetic (Plan-19d).
 *
 * Nigeria alone has 811 regions — 37 states and 774 LGAs. The endpoint sends them flat
 * and unpaginated (one response beats 37 expand requests); this module turns that into a
 * tree and answers the two questions the picker asks: what is selected, and what does a
 * given address match.
 */

export interface RegionRow {
  id: number;
  country_code: string;
  name: string;
  level: "state" | "area";
  parent: number | null;
  is_active: boolean;
}

export interface StateNode {
  state: RegionRow;
  areas: RegionRow[];
}

/** States with their areas, both alphabetical. */
export function buildTree(regions: RegionRow[]): StateNode[] {
  const states = regions.filter((r) => r.level === "state");
  const byParent = new Map<number, RegionRow[]>();
  for (const area of regions.filter((r) => r.level === "area")) {
    if (area.parent === null) continue;
    byParent.set(area.parent, [...(byParent.get(area.parent) ?? []), area]);
  }
  return states
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((state) => ({
      state,
      areas: (byParent.get(state.id) ?? []).sort((a, b) => a.name.localeCompare(b.name)),
    }));
}

export type StateSelection = "all" | "some" | "none";

/** "LGA" -> "LGAs", "County" -> "counties" — for "N counties" expander text.
 * Acronym labels keep their case; words go lowercase mid-sentence. */
export function pluralLabel(label: string): string {
  if (label === label.toUpperCase()) return `${label}s`;
  const lower = label.toLowerCase();
  return lower.endsWith("y") ? `${lower.slice(0, -1)}ies` : `${lower}s`;
}

/** Mid-sentence form: "State" -> "state", but "LGA" stays "LGA". */
export function lowerLabel(label: string): string {
  return label === label.toUpperCase() ? label : label.toLowerCase();
}

/** The regions of one country, for building that country's tree. */
export function regionsOf(regions: RegionRow[], countryCode: string): RegionRow[] {
  return regions.filter((r) => r.country_code === countryCode);
}

/** Whether a state is fully, partly or not covered — the tri-state a parent checkbox
 *  needs. "Some" is the one that matters: it is how mixed granularity is visible at all. */
export function stateSelection(node: StateNode, selected: Set<number>): StateSelection {
  if (selected.has(node.state.id)) return "all";
  if (!node.areas.length) return "none";
  const hits = node.areas.filter((a) => selected.has(a.id)).length;
  if (hits === 0) return "none";
  return hits === node.areas.length ? "all" : "some";
}

/**
 * Does this option serve the given state/area?
 *
 * Mirrors the backend's ancestor walk (`delivery/services._covered_region_ids`): an
 * address matches if the option covers its whole country, its state, or that exact area.
 * This is the "test an address" widget's answer, and it is a MIRROR — the backend decides
 * for real at checkout.
 */
export function coversAddress(
  input: { countryCode: string; stateId: number | null; areaId: number | null },
  coverage: { countryCodes: string[]; regionIds: Set<number> },
): boolean {
  if (coverage.countryCodes.includes(input.countryCode)) return true;
  if (input.stateId !== null && coverage.regionIds.has(input.stateId)) return true;
  if (input.areaId !== null && coverage.regionIds.has(input.areaId)) return true;
  return false;
}
