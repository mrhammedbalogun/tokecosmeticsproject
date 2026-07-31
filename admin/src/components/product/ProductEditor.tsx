"use client";

/**
 * The product editor shell: the tab strip, the form state every tab shares, and the save.
 *
 * ── TAB STATE IS LOCAL, NOT IN THE URL (17a design decision 3) ───────────────────────
 *
 * This deliberately contradicts `/settings/audit`, where filters live in the URL because
 * the URL should be the truth about what is on screen. A FORM is different: URL-driven
 * tabs make switching a NAVIGATION, and navigation destroys unsaved edits. Losing a
 * half-written description because somebody clicked "Availability" is a data-loss bug, not
 * a UX wrinkle. So the panels show and hide, and the cost — you cannot link to a tab — is
 * accepted.
 *
 * ── ONE COMPONENT OWNS THE STATE FOR EVERY TAB ──────────────────────────────────────
 *
 * The panels are presentational children taking values and an `onChange`. Giving each tab
 * its own form state would reintroduce exactly the problem the decision above avoids.
 *
 * ── WHAT SAVES WHEN (17a design decision 1) ─────────────────────────────────────────
 *
 * The product's own fields save together on Save. Variants, prices, images and stock are
 * separate resources that take effect immediately — and the UI must make that obvious
 * rather than hide it, which is what the unsaved-changes bar is for.
 */
import { useCallback, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { AvailabilityPanel } from "@/components/product/AvailabilityPanel";
import { ContentPanel } from "@/components/product/ContentPanel";
import { DetailsPanel } from "@/components/product/DetailsPanel";
import { ImagesPanel } from "@/components/product/ImagesPanel";
import { OptionEditor } from "@/components/product/OptionEditor";
import { cellKey, PricesPanel } from "@/components/product/PricesPanel";
import { SeoPanel } from "@/components/product/SeoPanel";
import { StockAdjustModal } from "@/components/product/StockAdjustModal";
import { VariantsPanel } from "@/components/product/VariantsPanel";
import type { AdjustResult } from "@/app/(shell)/products/[slug]/stock-actions";
import type { AdjustErrors } from "@/lib/stock-adjust";
import type { ImageResult, ProductImage } from "@/app/(shell)/products/[slug]/image-actions";
import type { PriceWriteResult } from "@/app/(shell)/products/[slug]/price-actions";
import { positionWrites, reorder, sortImages } from "@/lib/product-images";
import {
  amountChanged,
  buildPriceGrid,
  validateAmount,
  type Cell,
  type PriceRow,
  type VariantRow,
} from "@/lib/product-prices";
import { warehouseColumns, type StockRow } from "@/lib/product-stock";
import { deriveAxes, validateAxes, type Axis } from "@/lib/variant-matrix";
import {
  isDirty,
  toFormValues,
  type EditableField,
  type ProductDetail,
  type ProductFormValues,
} from "@/lib/product-form";
import type { CategoryRef, CountryRef, TagRef } from "@/lib/reference";

export interface SaveResult {
  savedSlug?: string;
  savedAt?: number;
  errors?: { fields: Partial<Record<EditableField, string>>; banner?: string };
}

const TABS = [
  { id: "details", label: "Details" },
  { id: "availability", label: "Availability" },
  { id: "variants", label: "Variants" },
  { id: "prices", label: "Prices" },
  { id: "content", label: "Content" },
  { id: "images", label: "Images" },
  { id: "seo", label: "SEO" },
] as const;

export interface ImageActions {
  upload: (slug: string, formData: FormData) => Promise<ImageResult<ProductImage>>;
  update: (
    id: number,
    patch: { alt?: string; position?: number },
  ) => Promise<ImageResult<ProductImage>>;
  remove: (id: number) => Promise<ImageResult<null>>;
}

type TabId = (typeof TABS)[number]["id"];

export function ProductEditor({
  product,
  categories,
  tags,
  countries,
  siteUrl,
  initialImages,
  imageActions,
  variants,
  stock,
  initialPrices,
  currencies,
  savePrice,
  adjustStock,
  save,
}: {
  product: ProductDetail;
  categories: CategoryRef[];
  tags: TagRef[];
  countries: CountryRef[];
  /** Storefront origin, for the SEO preview's URL line. */
  siteUrl: string;
  initialImages: ProductImage[];
  imageActions: ImageActions;
  variants: VariantRow[];
  stock: StockRow[];
  initialPrices: PriceRow[];
  currencies: readonly string[];
  savePrice: (input: {
    priceId: number | null;
    variantId: number;
    currency: string;
    amount: string;
    productSlug: string;
  }) => Promise<PriceWriteResult>;
  adjustStock: (input: {
    stockItemId: number;
    quantity: number;
    reason: string;
    note: string;
  }) => Promise<AdjustResult>;
  /** The Server Function. Injected so the component is testable without a server. */
  save: (slug: string, values: ProductFormValues) => Promise<SaveResult>;
}) {
  const router = useRouter();
  const initial = useMemo(() => toFormValues(product), [product]);

  const [tab, setTab] = useState<TabId>("details");
  const [values, setValues] = useState<ProductFormValues>(initial);
  const [baseline, setBaseline] = useState<ProductFormValues>(initial);
  const [result, setResult] = useState<SaveResult>({});
  const [pending, startTransition] = useTransition();

  // IMAGE STATE LIVES HERE, not in ImagesPanel, because that panel unmounts whenever
  // another tab is shown — state inside it would not survive a tab switch, and an upload
  // would appear to vanish on the way to Details and back.
  const [images, setImages] = useState<ProductImage[]>(() => sortImages(initialImages));
  const [imageError, setImageError] = useState<string | null>(null);
  // ITS OWN TRANSITION, not the save's. Sharing one would put the Save button into
  // "Saving…" and disable it while an image uploaded — announcing a write that is not
  // happening, on the one tab whose whole point is that it does NOT save with the form.
  const [imageBusy, startImageTransition] = useTransition();

  /** Every image write funnels through here, so there is one place that clears the
   *  previous error and refuses to leave a failure silent. */
  const runImageWrite = (work: () => Promise<string | null>) => {
    setImageError(null);
    startImageTransition(async () => {
      setImageError(await work());
    });
  };

  const onUpload = (file: File, alt: string) => {
    const formData = new FormData();
    formData.append("image", file);
    if (alt) formData.append("alt", alt);
    runImageWrite(async () => {
      const res = await imageActions.upload(baseline.slug, formData);
      if (!res.ok) return res.error;
      setImages((current) => sortImages([...current, res.value]));
      return null;
    });
  };

  const onAlt = (id: number, alt: string) => {
    runImageWrite(async () => {
      const res = await imageActions.update(id, { alt });
      if (!res.ok) return res.error;
      setImages((current) => current.map((i) => (i.id === id ? res.value : i)));
      return null;
    });
  };

  const onDelete = (id: number) => {
    runImageWrite(async () => {
      const res = await imageActions.remove(id);
      if (!res.ok) return res.error;
      setImages((current) => current.filter((i) => i.id !== id));
      return null;
    });
  };

  // --- the option matrix (17b) ---------------------------------------------------------
  //
  // Seeded from the variants the product already has, then held here rather than in the
  // panel: the Variants tab unmounts on every tab switch, and a half-defined matrix must
  // not evaporate on the way to Details and back. Nothing here is written until Apply.
  const [axes, setAxes] = useState<Axis[]>(() => deriveAxes(variants));
  const axisErrors = useMemo(() => validateAxes(axes), [axes]);

  // --- stock -------------------------------------------------------------------------
  //
  // The rows live here for the same reason the images and prices do: the Variants panel
  // unmounts on a tab switch, and an adjusted count must not revert on the way back.
  const [stockRows, setStockRows] = useState<StockRow[]>(stock);
  const [adjusting, setAdjusting] = useState<number | null>(null);
  const [adjustErrors, setAdjustErrors] = useState<AdjustErrors>({});
  const [adjustMessage, setAdjustMessage] = useState<string | null>(null);

  const adjustTarget = stockRows.find((row) => row.id === adjusting) ?? null;

  const openAdjust = (stockItemId: number) => {
    // Cleared on OPEN, not on close: a message left from a previous failure would greet
    // the next person to open the modal as though their own attempt had failed.
    setAdjustErrors({});
    setAdjustMessage(null);
    setAdjusting(stockItemId);
  };

  const submitAdjust = (values: { quantity: number; reason: string; note: string }) => {
    if (!adjustTarget) return;
    setAdjustErrors({});
    setAdjustMessage(null);
    startImageTransition(async () => {
      const res = await adjustStock({ stockItemId: adjustTarget.id, ...values });
      if (!res.ok) {
        setAdjustErrors(res.fieldErrors ?? {});
        setAdjustMessage(res.error ?? null);
        return;
      }
      // Adopt the saved row rather than assuming the typed number landed — `adjust`
      // returns the item as the database now holds it, and a concurrent reservation may
      // have moved `reserved` since the modal opened.
      if (res.item) {
        setStockRows((current) => current.map((row) => (row.id === res.item!.id ? res.item! : row)));
      }
      setAdjusting(null);
    });
  };

  // --- prices ----------------------------------------------------------------------
  //
  // Same reason as the images: this state must outlive a tab switch, and the panel does
  // not. Drafts are keyed by variant+currency so one cell's in-progress text never
  // disturbs another's.
  const [prices, setPrices] = useState<PriceRow[]>(initialPrices);
  const [priceDrafts, setPriceDrafts] = useState<Record<string, string>>({});
  const [priceErrors, setPriceErrors] = useState<Record<string, string>>({});
  const [busyCell, setBusyCell] = useState<string | null>(null);

  const grid = useMemo(
    () => buildPriceGrid(variants, prices, currencies),
    [variants, prices, currencies],
  );

  const onPriceDraft = (key: string, value: string) => {
    setPriceDrafts((current) => ({ ...current, [key]: value }));
    setPriceErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  };

  /** Commit on blur. Nothing is written for an untouched or unchanged cell — that would
   *  be a request and an audit row for typing nothing. */
  const onPriceCommit = (variantId: number, currency: string, cell: Cell) => {
    const key = cellKey(variantId, currency);
    const typed = priceDrafts[key];
    if (typed === undefined) return;

    const invalid = validateAmount(typed);
    if (invalid) {
      setPriceErrors((current) => ({ ...current, [key]: invalid }));
      return;
    }
    if (!amountChanged(cell, typed)) return;

    setBusyCell(key);
    startImageTransition(async () => {
      const res = await savePrice({
        priceId: cell.price?.id ?? null,
        variantId,
        currency,
        amount: typed.trim(),
        productSlug: baseline.slug,
      });
      setBusyCell(null);
      if (!res.ok || !res.price) {
        setPriceErrors((current) => ({
          ...current,
          [key]: res.error ?? "That price could not be saved.",
        }));
        return;
      }
      // Adopt the saved row — including its id, so a second edit of a cell that was
      // empty a moment ago PATCHes rather than POSTing a duplicate the unique constraint
      // would reject.
      const saved = res.price as PriceRow;
      setPrices((current) => {
        const without = current.filter((p) => p.id !== saved.id);
        return [...without, saved];
      });
      setPriceDrafts((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
    });
  };

  const onMove = (from: number, to: number) => {
    const next = reorder(images, from, to);
    const writes = positionWrites(images, next);
    if (!writes.length) return;

    // Optimistic, then reconciled: the arrows must feel like arrows. On failure the list
    // is put back exactly as it was, because a row that stays where it was dragged while
    // the database disagrees is the worst of both.
    const previous = images;
    setImages(next);
    runImageWrite(async () => {
      for (const write of writes) {
        const res = await imageActions.update(write.id, { position: write.position });
        if (!res.ok) {
          setImages(previous);
          return res.error;
        }
      }
      return null;
    });
  };

  const dirty = isDirty(values, baseline);

  const onChange = useCallback(
    <K extends keyof ProductFormValues>(field: K, value: ProductFormValues[K]) => {
      setValues((current) => ({ ...current, [field]: value }));
      // The previous save's field errors stop being true the moment somebody edits. Left
      // on screen they read as "still wrong", and people re-fix a field that is now fine.
      setResult((current) => (current.errors ? {} : current));
    },
    [],
  );

  const onSave = () => {
    startTransition(async () => {
      const next = await save(baseline.slug, values);
      setResult(next);
      if (next.savedSlug) {
        // The saved values become the new baseline, so the bar clears without a refetch.
        setBaseline(values);
        // The slug is the URL. `replace`, not `push`: the old slug now 404s, so leaving it
        // in history gives the back button a broken page.
        if (next.savedSlug !== baseline.slug) {
          router.replace(`/products/${next.savedSlug}`);
        }
      }
    });
  };

  const errors = result.errors?.fields ?? {};

  return (
    <div>
      <div className="flex items-center gap-1 border-b border-line" role="tablist">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm ${
              tab === id
                ? "border-accent font-medium text-accent"
                : "border-transparent text-muted hover:text-fg"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {result.errors?.banner && (
        <p className="mt-4 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-3 text-sm text-warn">
          {result.errors.banner}
        </p>
      )}

      <div className="mt-6">
        {tab === "details" && (
          <DetailsPanel
            values={values}
            errors={errors}
            onChange={onChange}
            categories={categories}
            tags={tags}
          />
        )}
        {tab === "availability" && (
          <AvailabilityPanel
            values={values}
            errors={errors}
            onChange={onChange}
            countries={countries}
          />
        )}
        {tab === "variants" && (
          <div className="space-y-6">
            <OptionEditor
              axes={axes}
              errors={axisErrors}
              onChange={setAxes}
              hasVariants={variants.length > 0}
            />
            <VariantsPanel
              variants={variants}
              stock={stockRows}
              warehouses={warehouseColumns(stockRows)}
              onAdjust={openAdjust}
            />
          </div>
        )}
        {tab === "prices" && (
          <PricesPanel
            grid={grid}
            currencies={currencies}
            drafts={priceDrafts}
            errors={priceErrors}
            busyKey={busyCell}
            onDraft={onPriceDraft}
            onCommit={onPriceCommit}
          />
        )}
        {tab === "content" && (
          <ContentPanel values={values} errors={errors} onChange={onChange} />
        )}
        {tab === "images" && (
          <ImagesPanel
            images={images}
            busy={imageBusy}
            error={imageError}
            onUpload={onUpload}
            onAlt={onAlt}
            onMove={onMove}
            onDelete={onDelete}
          />
        )}
        {tab === "seo" && (
          <SeoPanel values={values} errors={errors} onChange={onChange} siteUrl={siteUrl} />
        )}
      </div>

      <div className="sticky bottom-0 mt-6 flex items-center gap-3 border-t border-line bg-bg/95 py-3 backdrop-blur">
        <button
          type="button"
          onClick={onSave}
          disabled={pending || !dirty}
          className="rounded bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Saving…" : "Save"}
        </button>

        {dirty && !pending && (
          <span className="text-sm text-warn">Unsaved changes on this product.</span>
        )}
        {!dirty && result.savedAt && (
          <span className="text-sm text-ok" role="status">
            Saved.
          </span>
        )}
      </div>

      {adjustTarget && (
        <StockAdjustModal
          sku={adjustTarget.sku}
          warehouseName={adjustTarget.warehouse_name}
          currentQuantity={adjustTarget.quantity}
          reserved={adjustTarget.reserved}
          busy={imageBusy}
          serverErrors={adjustErrors}
          serverMessage={adjustMessage}
          onSubmit={submitAdjust}
          onClose={() => setAdjusting(null)}
        />
      )}
    </div>
  );
}
