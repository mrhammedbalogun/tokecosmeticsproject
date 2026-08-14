"use client";
import { useEffect, useRef, useState } from "react";
import { useCheckout } from "@/components/checkout/CheckoutContext";
import { useCart } from "@/hooks/useCart";
import { RegionSelect, type Region } from "@/components/checkout/RegionSelect";
import { AddressAutocompleteInput } from "@/components/address/AddressAutocompleteInput";
import { LgaMismatchNudge } from "@/components/address/LgaMismatchNudge";
import { PinConfirmMap, type LatLng } from "@/components/address/PinConfirmMap";
import { detectLgaMismatch } from "@/components/address/lgaMismatch";
import type { PlacePick } from "@/lib/googleMaps";
import {
  fieldConfigFor,
  summarizeAddress,
  type Address,
  type AddressFieldErrors,
} from "@/components/checkout/address-fields";
import { PhoneField } from "@/components/ui/PhoneField";

interface FormValues {
  label: string;
  first_name: string;
  last_name: string;
  phone: string;
  line1: string;
  line2: string;
  city_text: string;
  state_text: string;
  postcode: string;
  state_region?: number;
  area_region?: number;
}

const EMPTY_FORM: FormValues = {
  label: "",
  first_name: "",
  last_name: "",
  phone: "",
  line1: "",
  line2: "",
  city_text: "",
  state_text: "",
  postcode: "",
  state_region: undefined,
  area_region: undefined,
};

/** Step 2 of checkout: the delivery-address book + per-country "Add new address"
 * form (Plan-14 Task 7).
 *
 * - Loads the shopper's saved addresses (GET /api/addresses) and renders each as a
 *   selectable card. The default shipping address (if any) is highlighted on load,
 *   but — unlike SignInStep's silent auto-complete — nothing advances the step
 *   until the shopper actually clicks a card; addresses aren't a yes/no gate the
 *   way auth is, and a default can be stale (moved house, etc).
 * - Cards are `role="radio"` buttons rather than native `<input type="radio">`:
 *   a native radio's change event never fires again once it's already checked,
 *   which would make re-clicking the pre-highlighted default a dead end. Buttons
 *   fire on every click regardless of prior state.
 * - The address country is locked to the cart's shopping country (useCart) —
 *   changing it mid-checkout would restart pricing, so that lives in the country
 *   switcher, not here.
 */
export function AddressStep() {
  const { selections, setAddress, complete } = useCheckout();
  const { cart } = useCart();
  const country = cart.country;

  const [addresses, setAddresses] = useState<Address[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | undefined>(selections.addressId);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormValues>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<AddressFieldErrors>({});

  // Plan-32b slice 3: the pin (committed door coordinates), the LGA name Google
  // attached to the last Places pick (feeds the mismatch nudge), and the loaded
  // LGA objects (names + centroids) mirrored out of RegionSelect.
  const [pin, setPin] = useState<LatLng | null>(null);
  const [pickedLga, setPickedLga] = useState<string | null>(null);
  const [areas, setAreas] = useState<Region[]>([]);

  function handlePlacePick(p: PlacePick) {
    setForm((prev) => ({ ...prev, line1: p.line1 }));
    setPin({ lat: p.lat, lng: p.lng }); // a pick IS door coordinates — commit it
    setPickedLga(p.lgaName);
  }

  function resetPinState() {
    setPin(null);
    setPickedLga(null);
  }

  // One-shot mount load, mirroring SignInStep's checkedRef guard. All setState calls
  // below happen after the awaited fetch, not synchronously in the effect body.
  const loadedRef = useRef(false);
  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    (async () => {
      try {
        const res = await fetch("/api/addresses");
        const data: Address[] = res.ok ? await res.json().catch(() => []) : [];
        setAddresses(data);
        if (data.length === 0) {
          setShowForm(true);
        } else {
          const def = data.find((a) => a.is_default_shipping);
          if (def) setSelectedId((prev) => prev ?? def.id);
        }
      } catch {
        setAddresses([]);
        setShowForm(true);
      }
    })();
  }, []);

  // A saved address from before its country grew a region tree (GB/US/CA since the
  // Countries_breakdown work) has no state_region — which means only country-wide
  // delivery options can ever match it, and the day those are retired for state-scoped
  // ones the shopper would dead-end at the delivery step. Picking such an address
  // detours through a one-select "complete this address" panel instead.
  const [fixup, setFixup] = useState<Address | null>(null);
  const [fixupRegion, setFixupRegion] = useState<{
    state_region?: number;
    area_region?: number;
  }>({});
  const [fixupSaving, setFixupSaving] = useState(false);
  const [fixupError, setFixupError] = useState<string | null>(null);

  function handleSelect(addr: Address) {
    if (fieldConfigFor(addr.country_code).useRegions && !addr.state_region) {
      setSelectedId(addr.id);
      setFixup(addr);
      setFixupRegion({});
      setFixupError(null);
      return;
    }
    setFixup(null);
    setSelectedId(addr.id);
    setAddress(addr.id);
    complete(2, { addressDisplay: summarizeAddress(addr) });
  }

  async function saveFixup() {
    if (!fixup || !fixupRegion.state_region) return;
    setFixupSaving(true);
    setFixupError(null);
    try {
      const res = await fetch(`/api/addresses/${fixup.id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          state_region: fixupRegion.state_region,
          ...(fixupRegion.area_region ? { area_region: fixupRegion.area_region } : {}),
        }),
      });
      if (!res.ok) {
        const body: AddressFieldErrors = await res.json().catch(() => ({}));
        setFixupError(
          body.state_region?.join(" ") ??
            body.area_region?.join(" ") ??
            body.detail ??
            "The address could not be updated — please try again.",
        );
        return;
      }
      const updated: Address = await res.json();
      setAddresses((prev) => (prev ?? []).map((a) => (a.id === updated.id ? updated : a)));
      setFixup(null);
      setAddress(updated.id);
      complete(2, { addressDisplay: summarizeAddress(updated) });
    } catch {
      setFixupError("The address could not be updated — please try again.");
    } finally {
      setFixupSaving(false);
    }
  }

  function updateField<K extends keyof FormValues>(key: K, value: FormValues[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    setFieldErrors({});

    const cfg = fieldConfigFor(country);
    const payload: Record<string, unknown> = {
      country_code: country,
      line1: form.line1.trim(),
      first_name: form.first_name.trim(),
      phone: form.phone.trim(),
    };
    if (form.label.trim()) payload.label = form.label.trim();
    if (form.last_name.trim()) payload.last_name = form.last_name.trim();
    if (form.line2.trim()) payload.line2 = form.line2.trim();
    // NOT exclusive: GB/US/CA need the structured state AND city + postcode.
    if (cfg.useRegions) {
      if (form.state_region) payload.state_region = form.state_region;
      if (form.area_region) payload.area_region = form.area_region;
    }
    for (const f of cfg.textFields) {
      const v = form[f.name].trim();
      if (v) payload[f.name] = v;
    }
    if (pin) {
      payload.latitude = pin.lat.toFixed(6);
      payload.longitude = pin.lng.toFixed(6);
    }

    try {
      const res = await fetch("/api/addresses", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        const created: Address = await res.json();
        setAddresses((prev) => [...(prev ?? []), created]);
        setShowForm(false);
        setForm(EMPTY_FORM);
        resetPinState();
        handleSelect(created);
        return;
      }
      const body: AddressFieldErrors = await res.json().catch(() => ({}));
      setFieldErrors(body);
      const knownKeys: Array<keyof AddressFieldErrors> = [
        "label", "first_name", "last_name", "phone", "line1", "line2",
        "country_code", "state_region", "area_region", "city_text", "state_text", "postcode",
      ];
      if (body.detail) setFormError(body.detail);
      else if (!knownKeys.some((k) => body[k])) {
        setFormError("Something went wrong saving this address — please try again.");
      }
    } catch {
      setFormError("Something went wrong saving this address — please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (addresses === null) {
    return <p className="text-sm text-muted">Loading your addresses…</p>;
  }

  const cfg = fieldConfigFor(country);

  return (
    <div className="space-y-6">
      {addresses.length > 0 && (
        <div role="radiogroup" aria-label="Saved addresses" className="space-y-3">
          {addresses.map((addr) => {
            const checked = selectedId === addr.id;
            return (
              <button
                key={addr.id}
                type="button"
                role="radio"
                aria-checked={checked}
                onClick={() => handleSelect(addr)}
                className={`block w-full rounded-[var(--radius-card)] border p-4 text-left text-sm transition-colors ${
                  checked ? "border-accent bg-accent/5" : "border-line hover:border-accent/60"
                }`}
              >
                <span className="flex items-center gap-2 font-medium">
                  {addr.label || "Address"}
                  {addr.is_default_shipping && (
                    <span className="rounded-full bg-beige px-2 py-0.5 text-xs font-normal text-muted">
                      Default
                    </span>
                  )}
                </span>
                <span className="mt-1 block text-muted">{summarizeAddress(addr)}</span>
              </button>
            );
          })}
        </div>
      )}

      {fixup && (
        <div className="rounded-[var(--radius-card)] border border-accent/40 bg-accent/5 p-4">
          <p className="text-sm font-medium">Complete this address</p>
          <p className="mt-1 text-sm text-muted">
            This address was saved before we asked for a{" "}
            {(fieldConfigFor(fixup.country_code).regionLabels?.state ?? "state").toLowerCase()}{" "}
            — adding it unlocks every delivery option for your area.
          </p>
          <div className="mt-3">
            <RegionSelect
              country={fixup.country_code}
              stateValue={fixupRegion.state_region}
              areaValue={fixupRegion.area_region}
              labels={fieldConfigFor(fixup.country_code).regionLabels}
              onChange={setFixupRegion}
            />
          </div>
          {fixupError && (
            <p role="alert" className="mt-2 text-sm text-red-700">
              {fixupError}
            </p>
          )}
          <div className="mt-3 flex items-center gap-4">
            <button
              type="button"
              onClick={saveFixup}
              disabled={fixupSaving || !fixupRegion.state_region}
              className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              {fixupSaving ? "Saving…" : "Save and use this address"}
            </button>
            <button
              type="button"
              onClick={() => {
                setFixup(null);
                setSelectedId(undefined);
              }}
              className="text-sm text-muted underline hover:text-foreground"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {!showForm && addresses.length > 0 && (
        <button
          type="button"
          onClick={() => setShowForm(true)}
          className="text-sm font-medium text-accent underline hover:text-accent-strong"
        >
          Add new address
        </button>
      )}

      {showForm && (
        <form onSubmit={handleSubmit} className="space-y-4 border-t border-line pt-4" noValidate>
          <div aria-live="polite">
            {formError && (
              <p role="alert" className="text-sm text-red-700">
                {formError}
              </p>
            )}
          </div>

          <div>
            <span className="mb-1 block text-sm font-medium">Country</span>
            <input
              type="text"
              value={country}
              readOnly
              disabled
              className="w-full rounded-[var(--radius-card)] border border-line bg-beige/60 px-3 py-2 text-sm text-muted"
            />
            <p className="mt-1 text-xs text-muted">
              Changing country restarts pricing — do it from the country switcher.
            </p>
          </div>

          <div>
            <label htmlFor="addr-label" className="mb-1 block text-sm font-medium">
              Label (optional)
            </label>
            <input
              id="addr-label"
              type="text"
              value={form.label}
              onChange={(e) => updateField("label", e.target.value)}
              placeholder="Home, Office…"
              className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="addr-first-name" className="mb-1 block text-sm font-medium">
                First name
              </label>
              <input
                id="addr-first-name"
                type="text"
                value={form.first_name}
                onChange={(e) => updateField("first_name", e.target.value)}
                required
                autoComplete="given-name"
                className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
              />
              {fieldErrors.first_name && (
                <p role="alert" className="mt-1 text-sm text-red-700">
                  {fieldErrors.first_name.join(" ")}
                </p>
              )}
            </div>
            <div>
              <label htmlFor="addr-last-name" className="mb-1 block text-sm font-medium">
                Last name (optional)
              </label>
              <input
                id="addr-last-name"
                type="text"
                value={form.last_name}
                onChange={(e) => updateField("last_name", e.target.value)}
                autoComplete="family-name"
                className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
              />
              {fieldErrors.last_name && (
                <p role="alert" className="mt-1 text-sm text-red-700">
                  {fieldErrors.last_name.join(" ")}
                </p>
              )}
            </div>
          </div>

          <div>
            {/* form.phone holds the E.164 value (or "" while invalid), so the payload
                and the !form.phone submit gate never see display formatting. */}
            <PhoneField
              id="addr-phone"
              name="phone"
              label="Phone"
              defaultValue={form.phone}
              defaultCountry={country}
              required
              onValueChange={(e164) => updateField("phone", e164)}
            />
            {fieldErrors.phone && (
              <p role="alert" className="mt-1 text-sm text-red-700">
                {fieldErrors.phone.join(" ")}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="addr-line1" className="mb-1 block text-sm font-medium">
              Street address
            </label>
            {country === "NG" ? (
              // The Places assist (NG only, ruling 8). Free text stays valid —
              // the same field, just with suggestions layered on.
              <AddressAutocompleteInput
                id="addr-line1"
                value={form.line1}
                onChangeText={(v) => updateField("line1", v)}
                onPick={handlePlacePick}
                required
                className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
              />
            ) : (
              <input
                id="addr-line1"
                type="text"
                value={form.line1}
                onChange={(e) => updateField("line1", e.target.value)}
                required
                autoComplete="address-line1"
                className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
              />
            )}
            {fieldErrors.line1 && (
              <p role="alert" className="mt-1 text-sm text-red-700">
                {fieldErrors.line1.join(" ")}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="addr-line2" className="mb-1 block text-sm font-medium">
              Apartment, suite, etc. (optional)
            </label>
            <input
              id="addr-line2"
              type="text"
              value={form.line2}
              onChange={(e) => updateField("line2", e.target.value)}
              autoComplete="address-line2"
              className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
            />
          </div>

          {/* NOT exclusive: GB/US/CA render the structured state select AND
              city + postcode text fields (mirrors apps.core.address_rules). */}
          {cfg.useRegions && (
            <div>
              <RegionSelect
                country={country}
                stateValue={form.state_region}
                areaValue={form.area_region}
                labels={cfg.regionLabels}
                onChange={(v) =>
                  setForm((prev) => ({ ...prev, state_region: v.state_region, area_region: v.area_region }))
                }
                onAreasLoaded={setAreas}
              />
              {fieldErrors.state_region && (
                <p role="alert" className="mt-1 text-sm text-red-700">
                  {fieldErrors.state_region.join(" ")}
                </p>
              )}
              {fieldErrors.area_region && (
                <p role="alert" className="mt-1 text-sm text-red-700">
                  {fieldErrors.area_region.join(" ")}
                </p>
              )}
              {(() => {
                const mismatch = detectLgaMismatch(pickedLga, form.area_region, areas);
                const selected = areas.find((a) => a.id === form.area_region);
                if (!mismatch || !selected) return null;
                return (
                  <div className="mt-3">
                    <LgaMismatchNudge
                      suggested={mismatch}
                      selectedName={selected.name}
                      onAccept={(region) => {
                        updateField("area_region", region.id);
                        setPickedLga(null);
                      }}
                      onDismiss={() => setPickedLga(null)}
                    />
                  </div>
                );
              })()}
            </div>
          )}
          {cfg.textFields.length > 0 && (
            <div className="grid gap-4 sm:grid-cols-2">
              {cfg.textFields.map((f) => (
                <div key={f.name}>
                  <label htmlFor={`addr-${f.name}`} className="mb-1 block text-sm font-medium">
                    {f.label}
                  </label>
                  <input
                    id={`addr-${f.name}`}
                    type="text"
                    value={form[f.name]}
                    onChange={(e) => updateField(f.name, e.target.value)}
                    required={f.required}
                    className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
                  />
                  {fieldErrors[f.name] && (
                    <p role="alert" className="mt-1 text-sm text-red-700">
                      {fieldErrors[f.name]?.join(" ")}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* The confirm-your-pin map (ruling 2): opens once we have ANY anchor —
              a Places pick (precise) or the chosen LGA's centroid (approximate).
              NG only; degrades to nothing when neither exists yet. */}
          {country === "NG" &&
            (() => {
              const selectedArea = areas.find((a) => a.id === form.area_region);
              const centroid =
                selectedArea?.latitude != null && selectedArea?.longitude != null
                  ? {
                      lat: parseFloat(selectedArea.latitude),
                      lng: parseFloat(selectedArea.longitude),
                    }
                  : null;
              const center = pin ?? centroid;
              if (!center || Number.isNaN(center.lat) || Number.isNaN(center.lng)) return null;
              return (
                <div>
                  <span className="mb-1 block text-sm font-medium">Delivery pin</span>
                  <PinConfirmMap
                    center={center}
                    precise={pin !== null}
                    value={pin}
                    onChange={setPin}
                  />
                </div>
              );
            })()}

          <div className="flex items-center gap-4">
            <button
              type="submit"
              disabled={submitting || !form.line1 || !form.first_name || !form.phone}
              className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? "Saving…" : "Save address"}
            </button>
            {addresses.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setForm(EMPTY_FORM);
                  resetPinState();
                  setFormError(null);
                  setFieldErrors({});
                }}
                className="text-sm text-muted underline hover:text-foreground"
              >
                Cancel
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}
