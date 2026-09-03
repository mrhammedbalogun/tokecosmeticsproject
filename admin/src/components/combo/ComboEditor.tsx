"use client";

/**
 * The combo builder: one screen, four steps down the page, in the order the job happens.
 *
 * ── WHY THIS IS A PAGE AND NOT A TAB STRIP ──────────────────────────────────────────
 *
 * The product editor uses tabs because a product has seven unrelated concerns and nobody
 * touches all of them at once. A combo has ONE concern with four stages, and every stage
 * feeds the next: what is in the box decides what it costs, and which markets it sells in
 * decides which prices need setting. Hiding the items behind a tab while somebody sets a
 * price is how a bundle gets priced for a box that changed.
 *
 * ── WHAT SAVES WHEN ─────────────────────────────────────────────────────────────────
 *
 * Everything except the image saves together, on Save — items included. The backend
 * writes the item and price sets wholesale inside one audited transaction, so there is no
 * half-saved bundle. The image is its own route (a nested array does not survive a
 * multipart encoding) and takes effect immediately, which the panel says out loud.
 */
import { useCallback, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { RichTextField } from "@/components/RichTextField";
import { ComboItemsPanel } from "@/components/combo/ComboItemsPanel";
import { ComboPricingPanel } from "@/components/combo/ComboPricingPanel";
import { ProductPicker, type PickedVariant } from "@/components/combo/ProductPicker";
import {
  orderMarkets,
  previewPricing,
  STATUSES,
  type ComboDetail,
  type ComboItemRow,
  type ComboStatus,
  type PickerProduct,
} from "@/lib/combos";
import { UPLOAD_CAP_BYTES, downscaleImage, fileSizeMb } from "@/lib/image";
import type { CountryRef } from "@/lib/reference";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

export interface SaveResult {
  ok?: boolean;
  error?: string;
  fieldErrors?: Record<string, string>;
}

interface FormValues {
  name: string;
  slug: string;
  status: ComboStatus;
  is_featured: boolean;
  short_description: string;
  description: string;
  discount_percent: string;
  available_countries: string[];
  seo_title: string;
  seo_description: string;
}

function initialValues(combo: ComboDetail): FormValues {
  return {
    name: combo.name,
    slug: combo.slug,
    status: combo.status,
    is_featured: combo.is_featured,
    short_description: combo.short_description,
    description: combo.description,
    // Trailing zeros off, so the box reads "10" rather than "10.00" — it is a number a
    // person types, not a money amount.
    discount_percent: String(Number(combo.discount_percent)),
    available_countries: [...combo.available_countries],
    seo_title: combo.seo_title,
    seo_description: combo.seo_description,
  };
}

export function ComboEditor({
  combo,
  countries,
  searchProducts,
  save,
  uploadImage,
  storefrontOrigin,
}: {
  combo: ComboDetail;
  countries: CountryRef[];
  searchProducts: (term: string) => Promise<PickerProduct[]>;
  save: (payload: unknown) => Promise<SaveResult>;
  uploadImage: (formData: FormData) => Promise<SaveResult>;
  storefrontOrigin: string;
}) {
  const router = useRouter();
  const [values, setValues] = useState<FormValues>(() => initialValues(combo));
  const [items, setItems] = useState<ComboItemRow[]>(() => [...combo.items]);
  const [pinned, setPinned] = useState<Record<string, string>>(() =>
    Object.fromEntries(combo.prices.map((p) => [p.country, String(Number(p.amount).toFixed(2))])),
  );
  const [result, setResult] = useState<SaveResult>({});
  const [pending, startTransition] = useTransition();

  const allMarkets = useMemo(
    () => orderMarkets(countries.map((c) => c.code)),
    [countries],
  );
  // The markets to price: the restriction if there is one, otherwise every market —
  // `available_countries` empty means EVERYWHERE (see the Availability note below).
  const pricedMarkets = values.available_countries.length
    ? orderMarkets(values.available_countries)
    : allMarkets;
  const homeMarket = pricedMarkets[0] ?? "NG";
  const homeSymbol =
    countries.find((c) => c.code === homeMarket)?.currency?.symbol ?? "";

  const set = useCallback(<K extends keyof FormValues>(key: K, value: FormValues[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setResult({});
  }, []);

  const addPicked = ({ product, variant }: PickedVariant) => {
    if (items.some((i) => i.variant === variant.id)) return;
    setItems((prev) => [
      ...prev,
      {
        variant: variant.id,
        quantity: 1,
        product_name: product.name,
        product_slug: product.slug,
        variant_name: variant.name,
        sku: variant.sku,
        option_values: variant.option_values,
        image: variant.image ?? product.image,
        prices: variant.prices,
      },
    ]);
    setResult({});
  };

  const setQuantity = (variantId: number, quantity: number) =>
    setItems((prev) =>
      prev.map((i) => (i.variant === variantId ? { ...i, quantity } : i)),
    );

  const removeItem = (variantId: number) =>
    setItems((prev) => prev.filter((i) => i.variant !== variantId));

  const moveItem = (variantId: number, direction: -1 | 1) =>
    setItems((prev) => {
      const index = prev.findIndex((i) => i.variant === variantId);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });

  const toggleMarket = (code: string) =>
    set(
      "available_countries",
      values.available_countries.includes(code)
        ? values.available_countries.filter((c) => c !== code)
        : [...values.available_countries, code],
    );

  const onSave = () =>
    startTransition(async () => {
      const payload = {
        ...values,
        discount_percent: values.discount_percent === "" ? "0" : values.discount_percent,
        items: items.map((i, index) => ({
          variant: i.variant,
          quantity: i.quantity,
          position: index,
        })),
        // Only markets actually pinned, and only where the box holds a number. An empty
        // box is "automatic", not "free".
        prices: Object.entries(pinned)
          .filter(([market, amount]) => amount !== "" && pricedMarkets.includes(market))
          .map(([country, amount]) => ({ country, amount })),
      };
      const outcome = await save(payload);
      setResult(outcome);
      if (outcome.ok) router.refresh();
    });

  const preview = previewPricing(
    items,
    pricedMarkets,
    Number(values.discount_percent) || 0,
    pinned,
  );
  const homePreview = preview.find((p) => p.market === homeMarket);
  const unsellableMarkets = preview.filter((p) => p.componentsTotal === null);

  return (
    <div className="pb-24">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link
            href="/combos"
            className="text-xs text-muted underline-offset-2 hover:underline"
          >
            ← Combos
          </Link>
          <h1 className="mt-2 text-lg font-semibold tracking-tight">{values.name}</h1>
          <p className="mt-1 text-sm text-muted">
            <a
              href={`${storefrontOrigin}/combo/${combo.slug}`}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-2"
            >
              /combo/{combo.slug}
            </a>
            {combo.status !== "active" && " — not live until you set it to Active"}
          </p>
        </div>

        {homePreview?.amount != null && (
          <div className="rounded-[var(--radius-card)] border border-accent/30 bg-accent/5 px-4 py-3 text-right">
            <p className="text-xs text-muted">Price in {homeMarket}</p>
            <p className="text-lg font-semibold tabular-nums">
              {homeSymbol}
              {homePreview.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </p>
            <p className="text-xs text-accent tabular-nums">
              saves {homeSymbol}
              {(homePreview.saving ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </p>
          </div>
        )}
      </div>

      {/* Why the shop is not showing this, when the price panel looks perfectly healthy.
          Rendered from the SERVER's own `available_in` answer rather than re-derived
          here, so the banner cannot disagree with the storefront. It is a warning and
          not a refusal: building a bundle ahead of a product launch is a real workflow,
          and the draft component is exactly how that looks while it is in progress. */}
      {(combo.blockers ?? []).length > 0 && (
        <div className="mt-4 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-3">
          <p className="text-sm font-medium text-warn">
            {combo.status === "active"
              ? "This combo is Active but customers cannot see it."
              : "Before this can go live:"}
          </p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-warn">
            {(combo.blockers ?? []).map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {result.error && (
        <p className="mt-4 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-3 text-sm text-warn">
          {result.error}
        </p>
      )}
      {result.ok && (
        <p className="mt-4 rounded-[var(--radius-card)] border border-accent/30 bg-accent/5 p-3 text-sm text-accent">
          Saved.
        </p>
      )}

      <Section n={1} title="The combo" hint="Name, picture and the copy customers read.">
        <div className="grid gap-4 lg:grid-cols-[1fr_220px]">
          <div className="space-y-4">
            <label className="block text-xs text-muted">
              Name
              <input
                type="text"
                value={values.name}
                onChange={(e) => set("name", e.target.value)}
                className={`mt-1 ${FIELD}`}
              />
              {result.fieldErrors?.name && (
                <span className="mt-1 block text-xs text-warn">{result.fieldErrors.name}</span>
              )}
            </label>

            <label className="block text-xs text-muted">
              Short description
              <textarea
                value={values.short_description}
                onChange={(e) => set("short_description", e.target.value)}
                rows={2}
                placeholder="One line, shown on the combo card."
                className={`mt-1 ${FIELD}`}
              />
            </label>

            <RichTextField
              label="Description"
              value={values.description}
              onChange={(html) => set("description", html)}
              placeholder="What this combo is for, and why these things go together."
            />
          </div>

          <ImageBox
            currentUrl={combo.image_url}
            upload={uploadImage}
            onUploaded={() => router.refresh()}
          />
        </div>
      </Section>

      <Section
        n={2}
        title="What's in it"
        hint="Search your catalogue, pick the exact size and option, set how many go in the box."
      >
        <div className="max-w-3xl space-y-4">
          <ProductPicker
            search={searchProducts}
            onPick={addPicked}
            alreadyPicked={items.map((i) => i.variant)}
            market={homeMarket}
            currencySymbol={homeSymbol}
          />
          <ComboItemsPanel
            items={items}
            market={homeMarket}
            currencySymbol={homeSymbol}
            onQuantity={setQuantity}
            onRemove={removeItem}
            onMove={moveItem}
          />
        </div>
      </Section>

      <Section
        n={3}
        title="Where it sells"
        hint="Tick nothing to sell it everywhere."
      >
        <div className="max-w-2xl">
          <p
            className={`rounded-[var(--radius-card)] border p-3 text-sm ${
              values.available_countries.length === 0
                ? "border-accent/30 bg-accent/10"
                : "border-line bg-surface"
            }`}
          >
            {values.available_countries.length === 0 ? (
              <>
                <strong>Sold in every market.</strong> Nothing is ticked, which means no
                restriction — not that the combo is hidden.
              </>
            ) : (
              <>
                Sold in <strong>{values.available_countries.length}</strong>{" "}
                {values.available_countries.length === 1 ? "market" : "markets"} only.
                Untick everything to sell it everywhere again.
              </>
            )}
          </p>

          <div className="mt-3 grid gap-1 sm:grid-cols-2">
            {countries.map((country) => (
              <label
                key={country.code}
                className="flex items-center gap-2 rounded border border-line bg-surface px-3 py-2 text-sm"
              >
                <input
                  type="checkbox"
                  checked={values.available_countries.includes(country.code)}
                  onChange={() => toggleMarket(country.code)}
                  className="h-4 w-4 rounded border-line"
                />
                <span>
                  {country.name}{" "}
                  <span className="text-xs text-muted">({country.code})</span>
                </span>
              </label>
            ))}
          </div>

          {unsellableMarkets.length > 0 && (
            <p className="mt-3 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-3 text-xs text-warn">
              {unsellableMarkets.map((m) => m.market).join(", ")}:{" "}
              {unsellableMarkets.length === 1 ? "this market" : "these markets"} cannot show
              the combo — not everything in the box is priced there. It will simply not
              appear to those shoppers.
            </p>
          )}
        </div>
      </Section>

      <Section
        n={4}
        title="Price"
        hint="Worked out from what's in the box. Change any market's number to fix it there."
      >
        <ComboPricingPanel
          items={items}
          countries={countries}
          markets={pricedMarkets}
          discountPercent={values.discount_percent}
          pinned={pinned}
          onDiscountPercent={(v) => set("discount_percent", v)}
          onPin={(market, amount) => {
            setPinned((prev) => ({ ...prev, [market]: amount }));
            setResult({});
          }}
          onUnpin={(market) => {
            setPinned((prev) => {
              const next = { ...prev };
              delete next[market];
              return next;
            });
            setResult({});
          }}
        />
      </Section>

      <Section n={5} title="Publishing" hint="Status, ordering, and how it looks in search.">
        <div className="max-w-2xl space-y-4">
          <div className="flex flex-wrap items-end gap-4">
            <label className="block text-xs text-muted">
              Status
              <select
                value={values.status}
                onChange={(e) => set("status", e.target.value as ComboStatus)}
                className={`mt-1 ${FIELD} w-40`}
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s[0].toUpperCase() + s.slice(1)}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex items-center gap-2 pb-1.5 text-sm">
              <input
                type="checkbox"
                checked={values.is_featured}
                onChange={(e) => set("is_featured", e.target.checked)}
                className="h-4 w-4 rounded border-line"
              />
              Featured
            </label>
          </div>

          <label className="block text-xs text-muted">
            SEO title
            <input
              type="text"
              value={values.seo_title}
              onChange={(e) => set("seo_title", e.target.value)}
              placeholder={values.name}
              className={`mt-1 ${FIELD}`}
            />
          </label>

          <label className="block text-xs text-muted">
            SEO description
            <textarea
              value={values.seo_description}
              onChange={(e) => set("seo_description", e.target.value)}
              rows={2}
              className={`mt-1 ${FIELD}`}
            />
          </label>
        </div>
      </Section>

      {/* `left-0 md:left-56` rather than `inset-x-0`: the shell's sidebar is `w-56` and
          sits beside the content, so a full-width fixed bar would lie across it. It
          collapses to the full width below `md`, where the sidebar is hidden anyway. */}
      <div className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-surface/95 backdrop-blur md:left-56">
        <div className="flex items-center justify-between gap-4 px-6 py-3">
          <p className="text-xs text-muted">
            {items.length === 0
              ? "Add at least one product before this can be sold."
              : `${items.reduce((n, i) => n + i.quantity, 0)} items in the box`}
          </p>
          <button
            type="button"
            onClick={onSave}
            disabled={pending}
            className="rounded bg-accent px-5 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {pending ? "Saving…" : "Save combo"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Section({
  n,
  title,
  hint,
  children,
}: {
  n: number;
  title: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-8 border-t border-line pt-6">
      <div className="flex items-baseline gap-3">
        <span
          aria-hidden="true"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent"
        >
          {n}
        </span>
        <div>
          <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
          <p className="text-xs text-muted">{hint}</p>
        </div>
      </div>
      <div className="mt-4 pl-9">{children}</div>
    </section>
  );
}

function ImageBox({
  currentUrl,
  upload,
  onUploaded,
}: {
  currentUrl: string | null;
  upload: (formData: FormData) => Promise<SaveResult>;
  onUploaded: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const onFile = (file: File | undefined) => {
    if (!file) return;
    setError(null);
    startTransition(async () => {
      // THE SAME SHRINK-AND-CAP THE PRODUCT EDITOR USES, not a lighter version of it.
      // A phone photograph is routinely 8-12 MB; posting it raw dies at the platform's
      // request-body limit as an opaque failure partway through the upload, which reads
      // as "the admin is broken" rather than as "that file is too big".
      const staged = await downscaleImage(file);
      if (staged.size > UPLOAD_CAP_BYTES) {
        setError(
          `That image is ${fileSizeMb(staged)} even after shrinking — uploads over ` +
          "about 4 MB cannot reach the server. Export it as JPEG or resize it smaller " +
          "and try again.",
        );
        return;
      }
      const body = new FormData();
      body.set("image", staged);
      const outcome = await upload(body);
      if (outcome.error) setError(outcome.error);
      else onUploaded();
    });
  };

  return (
    <div>
      <p className="text-xs text-muted">Featured image</p>
      <div className="mt-1 overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface">
        {currentUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- media comes from the API's CDN
          <img src={currentUrl} alt="" className="aspect-square w-full object-cover" />
        ) : (
          <div className="flex aspect-square items-center justify-center text-xs text-muted">
            No image yet
          </div>
        )}
      </div>
      <label className="mt-2 block cursor-pointer rounded border border-line bg-surface px-3 py-1.5 text-center text-xs hover:border-accent">
        {pending ? "Uploading…" : currentUrl ? "Replace image" : "Upload image"}
        <input
          type="file"
          accept="image/*"
          disabled={pending}
          onChange={(e) => onFile(e.target.files?.[0])}
          className="hidden"
        />
      </label>
      <p className="mt-1 text-[11px] text-muted">
        Saves immediately — it does not wait for the Save button.
      </p>
      {error && <p className="mt-1 text-xs text-warn">{error}</p>}
    </div>
  );
}
