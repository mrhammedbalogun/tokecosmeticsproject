"use client";

/**
 * Standalone create/edit address form for the account address book (Plan-15d Task 2).
 * Same rendering rules as checkout's AddressStep (label/first_name/last_name/phone/
 * line1/line2 for every country, then per-country fields from address-fields.ts's
 * fieldConfigFor) — but AddressStep locks its country to the cart's shopping country,
 * where this form lets the shopper pick any of them, since a saved address does not
 * have to match today's shopping country.
 */
import { useState } from "react";
import { AccountRegionSelect } from "@/components/account/AccountRegionSelect";
import {
  fieldConfigFor,
  type Address,
  type AddressFieldErrors,
} from "@/components/checkout/address-fields";

interface FormValues {
  label: string;
  first_name: string;
  last_name: string;
  phone: string;
  line1: string;
  line2: string;
  country_code: string;
  city_text: string;
  state_text: string;
  postcode: string;
  state_region?: number;
  area_region?: number;
}

/**
 * The five markets backend/apps/core/migrations/0003_seed_countries_currencies.py seeds
 * — the same set address-fields.ts's fieldConfigFor supports directly (NG/GB/US/CA each
 * have a dedicated CountryFieldConfig; ZZ "International" is the DEFAULT_CONFIG fallback
 * that file names explicitly). There's no client-callable route for the live market list
 * (`getMarkets()` in lib/country.ts reads process.env.API_URL server-side only, and no BFF
 * route proxies it), so this mirrors that fixed set rather than adding a new fetch.
 */
const COUNTRY_OPTIONS: Array<{ code: string; name: string }> = [
  { code: "NG", name: "Nigeria" },
  { code: "GB", name: "United Kingdom" },
  { code: "US", name: "United States" },
  { code: "CA", name: "Canada" },
  { code: "ZZ", name: "International" },
];

const EMPTY_FORM: FormValues = {
  label: "", first_name: "", last_name: "", phone: "", line1: "", line2: "",
  country_code: "NG", city_text: "", state_text: "", postcode: "",
  state_region: undefined, area_region: undefined,
};

function formFromAddress(addr: Address): FormValues {
  return {
    label: addr.label ?? "",
    first_name: addr.first_name ?? "",
    last_name: addr.last_name ?? "",
    phone: addr.phone ?? "",
    line1: addr.line1,
    line2: addr.line2 ?? "",
    country_code: addr.country_code,
    city_text: addr.city_text ?? "",
    state_text: addr.state_text ?? "",
    postcode: addr.postcode ?? "",
    state_region: addr.state_region ?? undefined,
    area_region: addr.area_region ?? undefined,
  };
}

const KNOWN_ERROR_KEYS: Array<keyof AddressFieldErrors> = [
  "label", "first_name", "last_name", "phone", "line1", "line2",
  "country_code", "state_region", "area_region", "city_text", "state_text", "postcode",
];

export function AddressForm({
  initial,
  onSaved,
  onCancel,
}: {
  initial?: Address;
  onSaved: (address: Address) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<FormValues>(initial ? formFromAddress(initial) : EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<AddressFieldErrors>({});

  function updateField<K extends keyof FormValues>(key: K, value: FormValues[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  // Country-specific values belong to the old country's shape — carrying them over would
  // submit a stale state_region/area_region/postcode/city under the new country.
  function handleCountryChange(code: string) {
    setForm((prev) => ({
      ...prev,
      country_code: code,
      city_text: "", state_text: "", postcode: "",
      state_region: undefined, area_region: undefined,
    }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    setFieldErrors({});

    const cfg = fieldConfigFor(form.country_code);
    const payload: Record<string, unknown> = {
      country_code: form.country_code,
      line1: form.line1.trim(),
      first_name: form.first_name.trim(),
      phone: form.phone.trim(),
    };
    if (form.label.trim()) payload.label = form.label.trim();
    if (form.last_name.trim()) payload.last_name = form.last_name.trim();
    if (form.line2.trim()) payload.line2 = form.line2.trim();
    if (cfg.useRegions) {
      if (form.state_region) payload.state_region = form.state_region;
      if (form.area_region) payload.area_region = form.area_region;
    } else {
      for (const f of cfg.textFields) {
        const v = form[f.name].trim();
        if (v) payload[f.name] = v;
      }
    }

    const isEdit = Boolean(initial?.id);
    const url = isEdit ? `/api/addresses/${initial!.id}` : "/api/addresses";
    const method = isEdit ? "PATCH" : "POST";

    try {
      const res = await fetch(url, {
        method,
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        const saved: Address = await res.json();
        onSaved(saved);
        return;
      }
      const body: AddressFieldErrors = await res.json().catch(() => ({}));
      setFieldErrors(body);
      if (body.detail) setFormError(body.detail);
      else if (!KNOWN_ERROR_KEYS.some((k) => body[k])) {
        setFormError("Something went wrong saving this address — please try again.");
      }
    } catch {
      setFormError("Something went wrong saving this address — please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  const cfg = fieldConfigFor(form.country_code);

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <div aria-live="polite">
        {formError && (
          <p role="alert" className="text-sm text-red-700">
            {formError}
          </p>
        )}
      </div>

      <div>
        <label htmlFor="addr-form-country" className="mb-1 block text-sm font-medium">
          Country
        </label>
        <select
          id="addr-form-country"
          value={form.country_code}
          onChange={(e) => handleCountryChange(e.target.value)}
          className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
        >
          {COUNTRY_OPTIONS.map((c) => (
            <option key={c.code} value={c.code}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="addr-form-label" className="mb-1 block text-sm font-medium">
          Label (optional)
        </label>
        <input
          id="addr-form-label"
          type="text"
          value={form.label}
          onChange={(e) => updateField("label", e.target.value)}
          placeholder="Home, Office…"
          className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
        />
        {fieldErrors.label && (
          <p role="alert" className="mt-1 text-sm text-red-700">
            {fieldErrors.label.join(" ")}
          </p>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="addr-form-first-name" className="mb-1 block text-sm font-medium">
            First name
          </label>
          <input
            id="addr-form-first-name"
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
          <label htmlFor="addr-form-last-name" className="mb-1 block text-sm font-medium">
            Last name (optional)
          </label>
          <input
            id="addr-form-last-name"
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
        <label htmlFor="addr-form-phone" className="mb-1 block text-sm font-medium">
          Phone
        </label>
        <input
          id="addr-form-phone"
          type="tel"
          value={form.phone}
          onChange={(e) => updateField("phone", e.target.value)}
          required
          autoComplete="tel"
          className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
        />
        {fieldErrors.phone && (
          <p role="alert" className="mt-1 text-sm text-red-700">
            {fieldErrors.phone.join(" ")}
          </p>
        )}
      </div>

      <div>
        <label htmlFor="addr-form-line1" className="mb-1 block text-sm font-medium">
          Street address
        </label>
        <input
          id="addr-form-line1"
          type="text"
          value={form.line1}
          onChange={(e) => updateField("line1", e.target.value)}
          required
          autoComplete="address-line1"
          className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
        />
        {fieldErrors.line1 && (
          <p role="alert" className="mt-1 text-sm text-red-700">
            {fieldErrors.line1.join(" ")}
          </p>
        )}
      </div>

      <div>
        <label htmlFor="addr-form-line2" className="mb-1 block text-sm font-medium">
          Apartment, suite, etc. (optional)
        </label>
        <input
          id="addr-form-line2"
          type="text"
          value={form.line2}
          onChange={(e) => updateField("line2", e.target.value)}
          autoComplete="address-line2"
          className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
        />
      </div>

      {cfg.useRegions ? (
        <div>
          <AccountRegionSelect
            country={form.country_code}
            stateValue={form.state_region}
            areaValue={form.area_region}
            labels={cfg.regionLabels}
            onChange={(v) =>
              setForm((prev) => ({ ...prev, state_region: v.state_region, area_region: v.area_region }))
            }
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
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {cfg.textFields.map((f) => (
            <div key={f.name}>
              <label htmlFor={`addr-form-${f.name}`} className="mb-1 block text-sm font-medium">
                {f.label}
              </label>
              <input
                id={`addr-form-${f.name}`}
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

      <div className="flex items-center gap-4">
        <button
          type="submit"
          disabled={submitting || !form.line1 || !form.first_name || !form.phone}
          className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "Saving…" : "Save address"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-muted underline hover:text-foreground"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
