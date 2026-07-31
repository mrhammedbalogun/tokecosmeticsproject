/**
 * Ordering arithmetic for the Images tab. No fetching, no React.
 *
 * ── WHY A MOVE RENUMBERS EVERYTHING INSTEAD OF SWAPPING TWO ROWS ────────────────────
 *
 * `ProductImage.position` is a plain `PositiveIntegerField` with no uniqueness constraint,
 * and the 69 migrated products were populated by an importer — so gaps and DUPLICATES are
 * both possible, and `Meta.ordering = ["position", "id"]` resolves a tie by id rather than
 * by anything a person chose.
 *
 * Swapping the two positions involved in a move is correct only when positions are already
 * distinct and contiguous. Against `[0, 0, 0]` a swap changes nothing at all, and the row
 * springs back on reload with no error anywhere. Renumbering the whole list 0..n-1 makes
 * the displayed order true regardless of what it started as.
 *
 * `positionWrites` then narrows that to the rows whose number actually moved, so a normal
 * one-step move costs two PATCHes rather than one per image.
 */

export interface OrderedImage {
  id: number;
  position: number;
}

/** The list with `from` moved to `to`, renumbered 0..n-1. Out-of-range indices return the
 *  list unchanged rather than throwing — a double-click on the last row's "down" is a
 *  no-op, not an error. */
export function reorder<T extends OrderedImage>(images: T[], from: number, to: number): T[] {
  if (from === to) return images;
  if (from < 0 || from >= images.length) return images;
  if (to < 0 || to >= images.length) return images;

  const next = [...images];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next.map((image, index) => ({ ...image, position: index }));
}

/** Only the rows whose position differs from where they started. */
export function positionWrites(
  before: OrderedImage[],
  after: OrderedImage[],
): { id: number; position: number }[] {
  const was = new Map(before.map((image) => [image.id, image.position]));
  return after
    .filter((image) => was.get(image.id) !== image.position)
    .map((image) => ({ id: image.id, position: image.position }));
}

/**
 * The list as it should be displayed: the server's own ordering, made explicit.
 *
 * Mirrors `ProductImage.Meta.ordering = ["position", "id"]` — including the id tiebreak,
 * because duplicate positions are possible and a UI that ordered them differently from the
 * storefront would show a gallery nobody else sees.
 */
export function sortImages<T extends OrderedImage>(images: T[]): T[] {
  return [...images].sort((a, b) => a.position - b.position || a.id - b.id);
}
