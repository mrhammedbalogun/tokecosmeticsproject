/**
 * The LGA-mismatch nudge's brain (Plan-32b ruling 7): if a Places pick resolves
 * to a DIFFERENT LGA than the customer selected, we prompt to update — never
 * silently override, because Google's admin boundaries do not match our LGA
 * names cleanly and the LGA field is what prices delivery.
 */
import type { Region } from "@/components/checkout/RegionSelect";

/** Fold Google's "Ikeja Local Government Area" and our "Ikeja" into one key. */
export function normalizeLgaName(name: string): string {
  return name
    .toLowerCase()
    .replace(/local government area|local govt\.?|lga/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/**
 * The region the pick maps to, when it differs from the current selection.
 * Null means "no nudge": nothing picked, nothing selected yet, the names agree,
 * or Google named an LGA we cannot match to a priceable region — suggesting an
 * area we can't price would be a dead end, so we stay quiet and trust the human.
 */
export function detectLgaMismatch(
  pickedLgaName: string | null,
  selectedAreaId: number | undefined,
  areas: Region[],
): Region | null {
  if (!pickedLgaName || !selectedAreaId || areas.length === 0) return null;
  const picked = normalizeLgaName(pickedLgaName);
  if (!picked) return null;
  const selected = areas.find((a) => a.id === selectedAreaId);
  if (!selected || normalizeLgaName(selected.name) === picked) return null;
  return areas.find((a) => normalizeLgaName(a.name) === picked) ?? null;
}
