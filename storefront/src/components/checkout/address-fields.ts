/**
 * Client-side per-country address config (Plan-14 Task 7). The backend
 * (apps.core.address_rules.required_fields_for) is the single source of truth for
 * *validation* — this file only decides which inputs render, so it can never
 * disagree with a backend rule in a way that blocks submission (worst case: it
 * shows too few "required" hints and the shopper sees a 400 field error instead).
 *
 * apps.core.address_rules._BASE requires `line1`, `country_code`, `first_name`,
 * and `phone` for every country — the plan's per-country tables didn't list
 * first_name/phone, but the backend 400s without them, so AddressStep renders
 * them unconditionally alongside whatever this config adds.
 */

export interface Address {
  id: number;
  label?: string;
  first_name?: string;
  last_name?: string;
  phone?: string;
  line1: string;
  line2?: string;
  country_code: string;
  state_region?: number | null;
  area_region?: number | null;
  city_text?: string;
  state_text?: string;
  postcode?: string;
  is_default_shipping: boolean;
  is_default_billing: boolean;
}

/** Django field errors: `{ field: ["message", ...] }`, plus an optional top-level
 * `detail` for non-field problems. Mirrors SignInStep's ApiErrorBody pattern. */
export type AddressFieldErrors = Partial<
  Record<
    | "label"
    | "first_name"
    | "last_name"
    | "phone"
    | "line1"
    | "line2"
    | "country_code"
    | "state_region"
    | "area_region"
    | "city_text"
    | "state_text"
    | "postcode",
    string[]
  >
> & { detail?: string };

export interface TextFieldDef {
  name: "city_text" | "state_text" | "postcode";
  label: string;
  required: boolean;
}

export interface CountryFieldConfig {
  /** NG (the only seeded Region country at launch): render RegionSelect for
   * state_region/area_region instead of the free-text fields below. */
  useRegions: boolean;
  regionLabels?: { state: string; area: string };
  textFields: TextFieldDef[];
}

const NG_CONFIG: CountryFieldConfig = {
  useRegions: true,
  regionLabels: { state: "State", area: "LGA" },
  textFields: [],
};

const GB_CONFIG: CountryFieldConfig = {
  useRegions: false,
  textFields: [
    { name: "city_text", label: "City/Town", required: true },
    { name: "state_text", label: "County (optional)", required: false },
    { name: "postcode", label: "Postcode", required: true },
  ],
};

const US_CONFIG: CountryFieldConfig = {
  useRegions: false,
  textFields: [
    { name: "city_text", label: "City", required: true },
    { name: "state_text", label: "State (optional)", required: false },
    { name: "postcode", label: "ZIP code", required: true },
  ],
};

const CA_CONFIG: CountryFieldConfig = {
  useRegions: false,
  textFields: [
    { name: "city_text", label: "City", required: true },
    { name: "state_text", label: "Province (optional)", required: false },
    { name: "postcode", label: "Postal code", required: true },
  ],
};

/** Fallback for any market without a dedicated config above (e.g. the "ZZ" rest-of-
 * world market) — city is required (matches required_fields_for's non-NG default
 * branch), postcode is offered but optional since only GB/US/CA require it. */
const DEFAULT_CONFIG: CountryFieldConfig = {
  useRegions: false,
  textFields: [
    { name: "city_text", label: "City/Town", required: true },
    { name: "state_text", label: "State/Region (optional)", required: false },
    { name: "postcode", label: "Postcode (optional)", required: false },
  ],
};

const COUNTRY_FIELD_CONFIG: Record<string, CountryFieldConfig> = {
  NG: NG_CONFIG,
  GB: GB_CONFIG,
  US: US_CONFIG,
  CA: CA_CONFIG,
};

export function fieldConfigFor(countryCode: string): CountryFieldConfig {
  return COUNTRY_FIELD_CONFIG[countryCode.toUpperCase()] ?? DEFAULT_CONFIG;
}

/** Short "line1, city" summary for address book cards and the step-2 "Change"
 * line. NG addresses only carry region *ids* client-side (no name lookup here),
 * so they fall back to line1 alone rather than showing a raw id. */
export function summarizeAddress(addr: Address): string {
  const city = addr.city_text?.trim();
  return city ? `${addr.line1}, ${city}` : addr.line1;
}
