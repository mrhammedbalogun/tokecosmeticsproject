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
] as const;

export type EditableField = (typeof EDITABLE_FIELDS)[number];

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
}

/** The product as the detail endpoint returns it, narrowed to what the editor reads. */
export interface ProductDetail extends ProductFormValues {
  id: number;
  updated_at: string;
  variant_count: number;
  thumbnail: string | null;
  priced_currencies: string[];
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
  };
}

/** The PATCH body: every editable field, always. A partial body would make "cleared the
 *  last category" indistinguishable from "did not touch categories". */
export function toPatchPayload(values: ProductFormValues): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const field of EDITABLE_FIELDS) payload[field] = values[field];
  return payload;
}

/** Whether anything differs from what was loaded. Drives the "unsaved changes" state that
 *  17a design decision 1 requires the UI to make obvious. */
export function isDirty(a: ProductFormValues, b: ProductFormValues): boolean {
  for (const field of EDITABLE_FIELDS) {
    const left = a[field];
    const right = b[field];
    if (Array.isArray(left) && Array.isArray(right)) {
      // Order-insensitive: a checkbox grid produces whatever order the user clicked in,
      // and "NG,GB" against "GB,NG" is the same set of markets, not an edit.
      if (left.length !== right.length) return true;
      const sortedLeft = [...left].map(String).sort();
      const sortedRight = [...right].map(String).sort();
      if (sortedLeft.some((v, i) => v !== sortedRight[i])) return true;
    } else if (left !== right) {
      return true;
    }
  }
  return false;
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
