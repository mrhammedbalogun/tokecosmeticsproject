/** Shapes returned by the tax admin endpoints (Plan-37). Mirrors
 * apps/core/serializers.py — TaxSettingsSerializer / TaxCountryAdminSerializer. */

export interface TaxSettingsRow {
  charge_tax: boolean;
}

export interface TaxCountryRow {
  code: string;
  name: string;
  currency_code: string;
  is_default: boolean;
  is_rest_of_world: boolean;
  charge_tax: boolean;
  tax_rate_percent: string;
  prices_include_tax: boolean;
  tax_applies_to_delivery: boolean;
  tax_label: string;
}
