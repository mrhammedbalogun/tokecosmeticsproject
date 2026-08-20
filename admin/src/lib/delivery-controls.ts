/** Plan-41 delivery controls: block rules ("don't offer service X here") and fee
 * masks (a percentage on top of a service's real fee). Row shapes mirror the admin
 * API serializers verbatim. */

export interface DeliveryServiceRef {
  code: string;
  name: string;
  kind: "carrier" | "partner" | "store" | "manual";
}

export interface DeliveryBlockRow {
  id: number;
  service_code: string;
  service_name: string;
  country_code: string;
  state_region: number | null;
  state_name: string | null;
  area_region: number | null;
  area_name: string | null;
  is_active: boolean;
  updated_at: string;
}

export interface DeliveryFeeMaskRow {
  id: number;
  service_code: string;
  service_name: string;
  percent: string;
  is_active: boolean;
  updated_at: string;
}
