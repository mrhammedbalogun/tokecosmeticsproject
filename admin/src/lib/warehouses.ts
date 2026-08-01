/**
 * Warehouse shapes, and the two calculations that make this screen safe to use.
 *
 * ── WHY THERE IS ARITHMETIC HERE AT ALL ─────────────────────────────────────────────
 *
 * `inventory/services.reserve()` picks a warehouse with
 * `warehouse__is_active=True, warehouse__serves_countries=country`. So unticking NG on
 * Lagos HQ, or deactivating it, removes the only warehouse serving Nigeria and every
 * checkout in the only sellable market fails — with no error anywhere until a customer
 * tries to buy something. It looks like an ordinary checkbox edit and it is closer to a
 * kill switch (Plan-17c ruling 1b).
 *
 * The confirmation therefore has to name the consequence in plain words, and it has to be
 * COMPUTED from the other warehouses rather than asserted: "Nigeria" is not special, it is
 * merely the country that happens to have one warehouse today.
 */

export interface WarehouseRow {
  id: number;
  name: string;
  location_country: string;
  serves_countries: string[];
  priority: number;
  is_active: boolean;
  /** From the API: countries this warehouse is currently the LAST active server of. */
  countries_left_unserved: string[];
}

export interface WarehouseProposal {
  id: number;
  serves_countries: string[];
  is_active: boolean;
}

/**
 * The countries that would be left with NO active warehouse if this proposal were saved.
 *
 * Computed against the other warehouses as they stand — an inactive warehouse is not
 * cover, because `reserve()` skips it, and counting one would make the confirmation
 * reassure and be wrong.
 *
 * Note it is driven by the PROPOSAL, not by the API's `countries_left_unserved`: that
 * field describes the warehouse as saved, and the operator needs to know about the edit
 * they are about to make, including one that hands a country over rather than dropping it.
 */
export function strandedCountries(
  proposal: WarehouseProposal,
  all: WarehouseRow[],
): string[] {
  const others = all.filter((w) => w.id !== proposal.id && w.is_active);
  const coveredElsewhere = new Set(others.flatMap((w) => w.serves_countries));

  const current = all.find((w) => w.id === proposal.id);
  if (!current) return [];

  // Only countries this warehouse serves TODAY can be stranded by this edit; a country it
  // never served was already somebody else's problem or nobody's.
  const losing = current.serves_countries.filter(
    (code) => !proposal.is_active || !proposal.serves_countries.includes(code),
  );
  return losing.filter((code) => !coveredElsewhere.has(code)).sort();
}

/** True when the edit needs ruling 1b's confirmation: it changes coverage or activation.
 *  Renaming a warehouse or renumbering its priority does not. */
export function needsCoverageConfirmation(
  proposal: WarehouseProposal,
  all: WarehouseRow[],
): boolean {
  return strandedCountries(proposal, all).length > 0;
}

/**
 * Priorities shared by more than one ACTIVE warehouse.
 *
 * Allocation sorts by `(priority, pk)`, so a tie is resolved by primary key — which is to
 * say by the accident of which warehouse was created first. Production has both warehouses
 * at priority 1, so ZZ orders go to Lagos on pk order alone and nobody has ever chosen
 * that. The plan is explicit that this must WARN rather than merely be displayed: showing
 * a number nobody picked next to another identical number nobody picked does not tell
 * anyone a decision is owed.
 */
export function duplicatePriorities(all: WarehouseRow[]): number[] {
  const counts = new Map<number, number>();
  for (const w of all.filter((x) => x.is_active)) {
    counts.set(w.priority, (counts.get(w.priority) ?? 0) + 1);
  }
  return [...counts.entries()]
    .filter(([, n]) => n > 1)
    .map(([priority]) => priority)
    .sort((a, b) => a - b);
}

/** The active warehouses sharing a given priority, for naming them in the warning. */
export function warehousesAtPriority(all: WarehouseRow[], priority: number): WarehouseRow[] {
  return all.filter((w) => w.is_active && w.priority === priority);
}
