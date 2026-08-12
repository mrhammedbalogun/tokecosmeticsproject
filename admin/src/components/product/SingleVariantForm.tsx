"use client";

/**
 * The simple-product path: one variant, no options.
 *
 * Before this existed, a product with no option axes had NO way to get its first
 * variant — the matrix builder generates from `cartesian(axes)`, and zero axes is zero
 * combinations. Since prices, stock and weight all hang off variants, a "simple"
 * product (52 of 69 in production) was uncreatable in the admin without inventing a
 * fake axis. This form is that missing path: it creates exactly one variant with
 * empty `option_values` and `makeDefault: true`, then unmounts — the editor only
 * renders it while the product has no variants and no axes are being edited.
 *
 * The variant NAME defaults to the product's name, which is what the WooCommerce
 * import produced for every single-variant product; the storefront's variant-label
 * helper already handles that shape.
 *
 * LOCAL STATE, unlike the matrix drafts: this form exists only until its one create
 * lands, and a half-typed SKU lost to a tab switch costs three keystrokes, not a
 * matrix. Same trade OptionEditor makes for its value drafts.
 */
import { useState, useTransition } from "react";
import { parseWeightInput } from "@/lib/variant-weight";
import type { VariantCreateResult } from "@/app/(shell)/products/[slug]/variant-actions";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function SingleVariantForm({
  defaultSku,
  defaultName,
  onCreate,
}: {
  defaultSku: string;
  defaultName: string;
  onCreate: (input: {
    sku: string;
    name: string;
    weightGrams: number | null;
  }) => Promise<VariantCreateResult>;
}) {
  const [sku, setSku] = useState(defaultSku);
  const [name, setName] = useState(defaultName);
  const [weight, setWeight] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const submit = () => {
    const trimmedSku = sku.trim();
    const trimmedName = name.trim();
    if (!trimmedSku) return setError("A variant needs a SKU.");
    if (!trimmedName) return setError("A variant needs a name.");
    const parsed = parseWeightInput(weight);
    if (!parsed.ok) return setError(parsed.error);

    setError(null);
    startTransition(async () => {
      let res: VariantCreateResult;
      try {
        res = await onCreate({ sku: trimmedSku, name: trimmedName, weightGrams: parsed.grams });
      } catch {
        // The editor-wide rule: a dropped request becomes a message, never an
        // unhandled rejection that unmounts the page.
        res = { ok: false, error: "That did not reach the server — check the connection and retry." };
      }
      if (!res.ok) setError(res.error);
      // On success the parent adopts the variant and this form unmounts.
    });
  };

  return (
    <div className="rounded-[var(--radius-card)] border border-line p-4">
      <h2 className="text-sm font-medium">Create its variant</h2>
      <p className="mt-1 text-xs text-muted">
        Prices, stock and weight all live on a variant, so every product needs at least
        one. Most need exactly one — create it here. Only use the options builder below
        if this product comes in sizes or shades.
      </p>

      <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_1fr_8rem]">
        <label className="block text-xs text-muted">
          SKU
          <input
            type="text"
            value={sku}
            onChange={(e) => setSku(e.target.value)}
            disabled={pending}
            className={`mt-1 font-mono ${FIELD}`}
          />
        </label>
        <label className="block text-xs text-muted">
          Variant name
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={pending}
            className={`mt-1 ${FIELD}`}
          />
        </label>
        <label className="block text-xs text-muted">
          Weight (g)
          <input
            type="text"
            inputMode="numeric"
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
            disabled={pending}
            placeholder="optional"
            className={`mt-1 text-right tabular-nums ${FIELD}`}
          />
        </label>
      </div>

      {error && <p className="mt-2 text-xs text-warn">{error}</p>}

      <button
        type="button"
        onClick={submit}
        disabled={pending}
        className="mt-3 rounded bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
      >
        {pending ? "Creating…" : "Create variant"}
      </button>
    </div>
  );
}
