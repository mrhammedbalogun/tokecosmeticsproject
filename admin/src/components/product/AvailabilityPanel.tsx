/**
 * The Availability tab: which markets a product is sold in.
 *
 * ── THE TRAP THIS PANEL EXISTS TO AVOID ─────────────────────────────────────────────
 *
 * `Product.available_countries` is an M2M where **empty means EVERYWHERE**, not nowhere
 * (`catalog/models.py:132-134`, and Plan-05b's `sellable_in` reads it that way). A plain
 * checkbox grid renders "none ticked" and "sold in every market" identically, so somebody
 * clearing the last checkbox to withdraw a product would publish it to all of them.
 *
 * So the empty state is stated in words, in a highlighted panel, rather than left to be
 * inferred from unticked boxes. The restriction is opt-in: tick nothing and the product is
 * everywhere; tick some and it is only there.
 *
 * PRESENTATIONAL, like `DetailsPanel` — no state of its own.
 */
import type { PanelProps } from "@/components/product/DetailsPanel";
import type { CountryRef } from "@/lib/reference";

export function AvailabilityPanel({
  values,
  errors,
  onChange,
  countries,
}: PanelProps & { countries: CountryRef[] }) {
  const selected = values.available_countries;
  const everywhere = selected.length === 0;

  const toggle = (code: string) =>
    onChange(
      "available_countries",
      selected.includes(code) ? selected.filter((c) => c !== code) : [...selected, code],
    );

  return (
    <div className="max-w-2xl">
      <p
        className={`rounded-[var(--radius-card)] border p-3 text-sm ${
          everywhere ? "border-accent/30 bg-accent/10" : "border-line bg-surface"
        }`}
      >
        {everywhere ? (
          <>
            <strong>Sold in every market.</strong> Nothing is ticked, which means no
            restriction — not that the product is hidden. Tick markets below to limit it.
          </>
        ) : (
          <>
            Sold in <strong>{selected.length}</strong>{" "}
            {selected.length === 1 ? "market" : "markets"} only. Untick everything to make
            it available everywhere again.
          </>
        )}
      </p>

      <fieldset className="mt-4">
        <legend className="sr-only">Markets</legend>
        <div className="grid gap-1 sm:grid-cols-2">
          {countries.map((country) => (
            <label
              key={country.code}
              className="flex items-center gap-2 rounded border border-line bg-surface px-3 py-2 text-sm"
            >
              <input
                type="checkbox"
                checked={selected.includes(country.code)}
                onChange={() => toggle(country.code)}
                className="h-4 w-4 rounded border-line"
              />
              <span>
                {country.name}
                {/* ZZ is a real row in the country table and reads as a country code
                    nobody recognises. Naming it is the difference between an operator
                    knowing they have covered the rest of the world and guessing. */}
                {country.is_rest_of_world && (
                  <span className="ml-1 text-xs text-muted">(Rest of World)</span>
                )}
              </span>
              <span className="ml-auto text-xs text-muted">{country.code}</span>
            </label>
          ))}
        </div>
      </fieldset>

      {errors.available_countries && (
        <p className="mt-2 text-xs text-warn">{errors.available_countries}</p>
      )}

      <p className="mt-4 text-xs text-muted">
        A market also needs a price in its currency before the product appears there. The
        products list shows which are missing.
      </p>
    </div>
  );
}
