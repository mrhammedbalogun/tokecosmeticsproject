/**
 * The product editor's form shape, and the pure functions around it.
 *
 * ── WHY THE PAYLOAD IS BUILT FROM AN EXPLICIT FIELD LIST ────────────────────────────
 *
 * 17a design decision 1: the product's own fields (Details, Availability, Content, SEO)
 * save together as ONE `PATCH /admin/products/{slug}/`, while variants, prices, images and
 * stock are separate resources that save on their own.
 *
 * "One PATCH" must not become "PATCH everything the serializer accepts". The serializer
 * also writes `brand`, `related`, `published_at`, `legacy_source` and `legacy_wp_id`, and
 * a payload built by spreading form state would send `undefined` for whichever of those
 * the current tab set does not own — clobbering a value nobody on screen could see. So the
 * fields are listed, and a tab that is not built yet contributes nothing.
 *
 * `EDITABLE_FIELDS` grows in 17a task 4 (Content, SEO). Adding a field here and to
 * `ProductFormValues` is the whole change.
 */

export const STATUSES = ["draft", "active", "archived"] as const;
export type ProductStatus = (typeof STATUSES)[number];

/** Exactly the fields the built tabs own. Nothing else is sent. */
export const EDITABLE_FIELDS = [
  "name",
  "slug",
  "status",
  "short_description",
  "description",
  "is_featured",
  "categories",
  "tags",
  "available_countries",
  // Content and SEO, added in 17a task 4.
  "ingredients",
  "directions",
  "warnings",
  "specs",
  "faqs",
  "seo_title",
  "seo_description",
] as const;

export type EditableField = (typeof EDITABLE_FIELDS)[number];

/** `Product.specs` — `[{"label": .., "value": ..}]`. */
export interface SpecRow {
  label: string;
  value: string;
}

/** `Product.faqs` — `[{"q": .., "a": ..}]`. Short keys because that is what the model
 *  stores and what the storefront PDP already reads. */
export interface FaqRow {
  q: string;
  a: string;
}

export interface ProductFormValues {
  name: string;
  slug: string;
  status: ProductStatus;
  short_description: string;
  description: string;
  is_featured: boolean;
  categories: number[];
  tags: number[];
  available_countries: string[];
  ingredients: string;
  directions: string;
  warnings: string;
  specs: SpecRow[];
  faqs: FaqRow[];
  seo_title: string;
  seo_description: string;
}

/** The product as the detail endpoint returns it, narrowed to what the editor reads. */
export interface ProductDetail extends ProductFormValues {
  id: number;
  updated_at: string;
  variant_count: number;
  thumbnail: string | null;
  priced_currencies: string[];
}

/**
 * `specs` and `faqs` are `JSONField(default=list)`, so the database will hand back whatever
 * was last written to it — including, for the 69 migrated products, whatever the WordPress
 * importer produced.
 *
 * A missing key becomes `""` and the ROW SURVIVES. Dropping a half-populated row would
 * delete migrated content on the next save of an unrelated tab, which is the quietest kind
 * of data loss: nobody asked for it and nothing on screen said it happened. Only entries
 * that are not objects at all are discarded, because there is no field to show them in.
 */
export function normaliseSpecs(raw: unknown): SpecRow[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object")
    .map((row) => ({ label: str(row.label), value: str(row.value) }));
}

export function normaliseFaqs(raw: unknown): FaqRow[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object")
    .map((row) => ({ q: str(row.q), a: str(row.a) }));
}

function str(value: unknown): string {
  if (typeof value === "string") return value;
  // A number or boolean in a spec value is meaningful content badly typed, not garbage.
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

export function toFormValues(product: ProductDetail): ProductFormValues {
  return {
    name: product.name ?? "",
    slug: product.slug ?? "",
    status: product.status,
    short_description: product.short_description ?? "",
    description: product.description ?? "",
    is_featured: Boolean(product.is_featured),
    // Copied, not aliased. These arrays are handed to a client component that mutates
    // them; sharing the reference with the server-rendered product would make "has this
    // changed?" answer no after every edit.
    categories: [...(product.categories ?? [])],
    tags: [...(product.tags ?? [])],
    available_countries: [...(product.available_countries ?? [])],
    ingredients: product.ingredients ?? "",
    directions: product.directions ?? "",
    warnings: product.warnings ?? "",
    specs: normaliseSpecs(product.specs),
    faqs: normaliseFaqs(product.faqs),
    seo_title: product.seo_title ?? "",
    seo_description: product.seo_description ?? "",
  };
}

/** A row nobody filled in. Added by clicking "Add", then abandoned — it should not be
 *  written, and it should not count as an unsaved change either. */
export const isBlankSpec = (row: SpecRow) => !row.label.trim() && !row.value.trim();
export const isBlankFaq = (row: FaqRow) => !row.q.trim() && !row.a.trim();

/**
 * The PATCH body: every editable field, always. A partial body would make "cleared the
 * last category" indistinguishable from "did not touch categories".
 *
 * Wholly-blank spec and FAQ rows are dropped on the way out. A half-filled row is KEPT —
 * a question with no answer yet is work in progress, and silently discarding it would lose
 * what somebody just typed.
 */
export function toPatchPayload(values: ProductFormValues): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const field of EDITABLE_FIELDS) payload[field] = values[field];
  payload.specs = values.specs.filter((row) => !isBlankSpec(row));
  payload.faqs = values.faqs.filter((row) => !isBlankFaq(row));
  return payload;
}

/**
 * Fields whose value is a SET — membership matters, order does not. A checkbox grid
 * produces whatever order the user clicked in, and "NG,GB" against "GB,NG" is the same set
 * of markets, not an edit.
 *
 * `specs` and `faqs` are deliberately absent: they are ORDERED rows. A spec table reordered
 * is a real change, and treating it as none would leave the reorder unsaved with the bar
 * saying there was nothing to save.
 */
const SET_FIELDS = new Set<EditableField>(["categories", "tags", "available_countries"]);

/** Whether anything differs from what was loaded. Drives the "unsaved changes" state that
 *  17a design decision 1 requires the UI to make obvious. */
export function isDirty(a: ProductFormValues, b: ProductFormValues): boolean {
  for (const field of EDITABLE_FIELDS) {
    const left = a[field];
    const right = b[field];

    if (SET_FIELDS.has(field)) {
      const l = [...(left as (string | number)[])].map(String).sort();
      const r = [...(right as (string | number)[])].map(String).sort();
      if (l.length !== r.length || l.some((v, i) => v !== r[i])) return true;
      continue;
    }

    if (Array.isArray(left) && Array.isArray(right)) {
      // Ordered rows. Compared on their MEANINGFUL rows only, so adding an empty row and
      // then abandoning it does not arm the Save button over content that will be dropped
      // on the way out anyway.
      const l = meaningfulRows(field, left);
      const r = meaningfulRows(field, right);
      if (JSON.stringify(l) !== JSON.stringify(r)) return true;
      continue;
    }

    if (left !== right) return true;
  }
  return false;
}

function meaningfulRows(field: EditableField, rows: unknown[]): unknown[] {
  if (field === "specs") return (rows as SpecRow[]).filter((row) => !isBlankSpec(row));
  if (field === "faqs") return (rows as FaqRow[]).filter((row) => !isBlankFaq(row));
  return rows;
}

export function isProductStatus(value: string): value is ProductStatus {
  return (STATUSES as readonly string[]).includes(value);
}

/**
 * DRF's `{field: ["message"]}` mapped onto our field names, plus anything that could not
 * be attributed to a field.
 *
 * DRF also answers `{"detail": "…"}` for permission and throttle refusals, and
 * `{"non_field_errors": [...]}` for validators that span fields — the slug uniqueness
 * constraint among them. Both belong in the banner, not against an input.
 */
export interface FieldErrors {
  fields: Partial<Record<EditableField, string>>;
  banner?: string;
}

export function parseFieldErrors(data: unknown): FieldErrors {
  const out: FieldErrors = { fields: {} };
  if (!data || typeof data !== "object") return out;

  const body = data as Record<string, unknown>;
  const banner: string[] = [];

  for (const [key, value] of Object.entries(body)) {
    const message = Array.isArray(value)
      ? typeof value[0] === "string"
        ? value[0]
        : null
      : typeof value === "string"
        ? value
        : null;
    if (!message) continue;

    if ((EDITABLE_FIELDS as readonly string[]).includes(key)) {
      out.fields[key as EditableField] = message;
    } else {
      // Includes `detail`, `non_field_errors`, and any field a later tab owns but this
      // build does not render — which must still be SHOWN rather than swallowed, or a
      // save fails with a blank form and no explanation.
      banner.push(message);
    }
  }

  if (banner.length) out.banner = banner.join(" ");
  return out;
}
