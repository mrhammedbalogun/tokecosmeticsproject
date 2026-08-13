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
import { ForWhoPanel } from "@/components/product/ForWhoPanel";
import { ImagesPanel } from "@/components/product/ImagesPanel";
import {
  combinationKey,
  MatrixPreview,
  type RowState,
} from "@/components/product/MatrixPreview";
import { OptionEditor } from "@/components/product/OptionEditor";
import { RenamePanel } from "@/components/product/RenamePanel";
import { SingleVariantForm } from "@/components/product/SingleVariantForm";
import { cellKey, PricesPanel } from "@/components/product/PricesPanel";
import { SeoPanel } from "@/components/product/SeoPanel";
import { StockAdjustModal } from "@/components/product/StockAdjustModal";
import { VariantsPanel } from "@/components/product/VariantsPanel";
import { VideosPanel } from "@/components/product/VideosPanel";
import type { AdjustResult } from "@/app/(shell)/products/[slug]/stock-actions";
import type { AdjustErrors } from "@/lib/stock-adjust";
import type { ImageResult, ProductImage } from "@/app/(shell)/products/[slug]/image-actions";
import type { PriceWriteResult } from "@/app/(shell)/products/[slug]/price-actions";
import type { ProductVideo, VideoResult } from "@/app/(shell)/products/[slug]/video-actions";
import { UPLOAD_CAP_BYTES, downscaleImage, fileSizeMb } from "@/lib/image";
import type { MediaAssetRow } from "@/lib/media";
import { positionWrites, reorder, sortImages } from "@/lib/product-images";
import { uploadToS3 } from "@/lib/upload";
import type { UploadTicket } from "@/lib/upload-types";
import { VIDEO_CAP_BYTES } from "@/lib/video";
import {
  amountChanged,
  buildPriceGrid,
  validateAmount,
  type Cell,
  type PriceRow,
  type VariantRow,
} from "@/lib/product-prices";
import { warehouseColumns, type StockRow } from "@/lib/product-stock";
import {
  cartesian,
  deriveAxes,
  diffMatrix,
  mergeVariants,
  nameMismatches,
  remapOptions,
  renameSummary,
  suggestSku,
  validateAxes,
  variantName,
  type Axis,
  type MatrixDiff,
} from "@/lib/variant-matrix";
import type { VariantCreateResult } from "@/app/(shell)/products/[slug]/variant-actions";
import { parseWeightInput } from "@/lib/variant-weight";
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

/** What a write that never reached the server should say — a dropped connection, a
 *  request the platform refused, a mid-flight abort. Every awaited Server Function in
 *  this file must be wrapped so a rejection becomes this message rather than an
 *  unhandled rejection: with no error boundary catch, that unmounts the whole editor
 *  and takes the unsaved tabs with it (the "crash" of 2026-08-10). */
const UNREACHABLE = "That did not reach the server — check the connection and retry.";

const TABS = [
  { id: "details", label: "Details" },
  { id: "availability", label: "Availability" },
  { id: "variants", label: "Variants" },
  { id: "prices", label: "Prices" },
  { id: "content", label: "Content" },
  { id: "for-who", label: "For Who" },
  { id: "images", label: "Images" },
  { id: "videos", label: "Videos" },
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

/** All five injected, like `ImageActions`, so the component is testable without a
 *  server. `ticket`/`finalize` are the media library's own actions (the S3 leg between
 *  them runs in the browser — lib/upload.ts); `attach`/`update`/`remove` are the
 *  product-video bindings. */
export interface VideoActions {
  ticket: (input: {
    filename: string;
    size: number;
    container: "mp4" | "webm";
  }) => Promise<{ ticket?: UploadTicket; message?: string }>;
  finalize: (input: {
    key: string;
    originalName: string;
  }) => Promise<{ asset?: MediaAssetRow; warning?: string; message?: string }>;
  attach: (input: {
    productId: number;
    assetId: number;
    position: number;
  }) => Promise<VideoResult<ProductVideo>>;
  update: (id: number, patch: { position?: number }) => Promise<VideoResult<ProductVideo>>;
  remove: (id: number) => Promise<VideoResult<null>>;
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
  initialVideos,
  videoActions,
  variants,
  createVariant,
  updateVariant,
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
  initialVideos: ProductVideo[];
  videoActions: VideoActions;
  variants: VariantRow[];
  createVariant: (input: {
    productId: number;
    sku: string;
    name: string;
    optionValues: Record<string, string>;
    weightGrams: number | null;
    makeDefault: boolean;
  }) => Promise<VariantCreateResult>;
  updateVariant: (input: {
    variantId: number;
    optionValues?: Record<string, string>;
    name?: string;
    weightGrams?: number | null;
  }) => Promise<VariantCreateResult>;
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
      // The catch is load-bearing: a server action whose REQUEST is rejected (body over
      // the size limit, network drop) rejects on the client, and without it the failure
      // is silent — no error shown, the file apparently uploaded.
      try {
        setImageError(await work());
      } catch {
        setImageError(UNREACHABLE);
      }
    });
  };

  const onUpload = (file: File, alt: string) => {
    runImageWrite(async () => {
      const formData = new FormData();
      // Downscaled before it leaves the browser — a camera photo is routinely bigger
      // than the platform's request-body cap, and no PDP needs a 4000px original. A
      // file that STILL does not fit is refused here with the reason: the platform
      // kills an oversized request before the server can refuse it politely.
      const staged = await downscaleImage(file);
      if (staged.size > UPLOAD_CAP_BYTES) {
        return `That image is ${fileSizeMb(staged)} even after shrinking — uploads over about 4 MB cannot reach the server. Export it as JPEG or resize it smaller and try again.`;
      }
      formData.append("image", staged);
      if (alt) formData.append("alt", alt);
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

  // --- videos --------------------------------------------------------------------------
  //
  // Same shape as images (state here, panel presentational, immediate writes), with two
  // differences: the file's own bytes go browser → S3 between `ticket` and `finalize`
  // (Vercel kills bodies over ~4.5MB, so no video can ride a Server Function), and the
  // upload gets ITS OWN transition — sharing the images' would light "Working…" on the
  // Images tab for the minutes a 100MB file takes to climb.
  const [videos, setVideos] = useState<ProductVideo[]>(() => sortImages(initialVideos));
  const [videoError, setVideoError] = useState<string | null>(null);
  const [videoWarning, setVideoWarning] = useState<string | null>(null);
  const [videoProgress, setVideoProgress] = useState<number | null>(null);
  const [videoBusy, startVideoTransition] = useTransition();

  const runVideoWrite = (work: () => Promise<string | null>) => {
    setVideoError(null);
    startVideoTransition(async () => {
      // The same load-bearing catch as `runImageWrite`: a rejected request must become
      // a message, not an unhandled rejection that unmounts the whole editor.
      try {
        setVideoError(await work());
      } catch {
        setVideoError(UNREACHABLE);
      }
    });
  };

  const onVideoUpload = (file: File) => {
    setVideoWarning(null);
    runVideoWrite(async () => {
      if (file.size > VIDEO_CAP_BYTES) {
        return `That video is ${fileSizeMb(file)} — the limit is 128 MB. Re-encode it at 720p and about 2 Mbps (ffmpeg -crf 28 -movflags +faststart) and choose it again.`;
      }
      const container = file.name.toLowerCase().endsWith(".webm") ? "webm" : "mp4";
      const { ticket, message } = await videoActions.ticket({
        filename: file.name,
        size: file.size,
        container,
      });
      if (!ticket) return message ?? "The upload could not start.";

      setVideoProgress(0);
      try {
        await uploadToS3(ticket, file, setVideoProgress).promise;
      } catch (e) {
        return `${(e as Error).message} Large videos can't resume — choose it again.`;
      } finally {
        setVideoProgress(null);
      }

      const done = await videoActions.finalize({ key: ticket.key, originalName: file.name });
      if (!done.asset) return done.message ?? "The upload could not be verified.";
      // Non-fatal ("not faststart-encoded, browsers must download all of it before
      // playing") — the attach still proceeds, but silence here would hide the one
      // fact that explains a video that "never starts" on the storefront.
      if (done.warning) setVideoWarning(done.warning);

      const res = await videoActions.attach({
        productId: product.id,
        assetId: done.asset.id,
        position: videos.length,
      });
      if (!res.ok) return res.error;
      setVideos((current) => sortImages([...current, res.value]));
      return null;
    });
  };

  const onVideoMove = (from: number, to: number) => {
    const next = reorder(videos, from, to);
    const writes = positionWrites(videos, next);
    if (!writes.length) return;

    // Optimistic then reconciled, exactly like image reordering.
    const previous = videos;
    setVideos(next);
    runVideoWrite(async () => {
      for (const write of writes) {
        const res = await videoActions.update(write.id, { position: write.position });
        if (!res.ok) {
          setVideos(previous);
          return res.error;
        }
      }
      return null;
    });
  };

  const onVideoDelete = (id: number) => {
    runVideoWrite(async () => {
      const res = await videoActions.remove(id);
      if (!res.ok) return res.error;
      setVideos((current) => current.filter((v) => v.id !== id));
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

  // Variants created this session, so the grid and the SKU-collision check see them
  // without a page reload.
  const [newVariants, setNewVariants] = useState<VariantRow[]>([]);
  // Variants rewritten this session, keyed by id — so a rename shows on screen without a
  // reload and without mutating the server-rendered `variants` prop.
  const [updated, setUpdated] = useState<Record<number, VariantRow>>({});
  const allVariants = useMemo(
    // mergeVariants, not a plain spread: once the revalidated page data lands, the
    // server prop contains the variants created this session too, and concatenating
    // showed every fresh row twice (and doubled the next Generate's arithmetic).
    () => mergeVariants(variants, newVariants).map((v) => updated[v.id] ?? v),
    [variants, newVariants, updated],
  );

  // The preview is a SNAPSHOT, taken by Generate. Recomputing live on every keystroke
  // would rewrite the SKUs somebody is editing, and half-typed axes would churn the list.
  const [preview, setPreview] = useState<{ axes: Axis[]; diff: MatrixDiff } | null>(null);
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const [applying, setApplying] = useState(false);

  // Compared by value, not identity: `setAxes` produces a new array on every edit, so an
  // identity check would call every preview stale the moment anything was touched.
  const previewStale =
    preview !== null && JSON.stringify(preview.axes) !== JSON.stringify(axes);

  const onGenerate = () => {
    const diff = diffMatrix(cartesian(axes), allVariants);
    const taken = allVariants.map((v) => v.sku);
    const next: Record<string, RowState> = {};
    for (const combination of diff.missing) {
      const sku = suggestSku(product.slug, combination, taken);
      // Pushed onto `taken` as we go, or two combinations that truncate to the same base
      // would both be suggested the identical SKU and the second would 400 on Apply.
      taken.push(sku);
      next[combinationKey(combination)] = {
        sku,
        name: variantName(combination),
        weight: "",
        status: "pending",
      };
    }
    setRows(next);
    setPreview({ axes, diff });
  };

  const onApply = () => {
    if (!preview) return;
    setApplying(true);
    startImageTransition(async () => {
      // COUNTED LOCALLY, not read from `allVariants`. That is a `useMemo` over state, and
      // state set inside this loop is not visible to the next iteration's closure — so
      // reading it here marked EVERY generated variant as the default instead of only the
      // first, silently demoting each one as the next was created.
      let variantCount = allVariants.length;

      for (const combination of preview.diff.missing) {
        const key = combinationKey(combination);
        const row = rows[key];
        if (!row || row.status === "created") continue;

        // Parsed BEFORE the request, so a typo costs a red row and no API call —
        // and one bad weight does not strand the other rows, same as a SKU collision.
        const weight = parseWeightInput(row.weight);
        if (!weight.ok) {
          setRows((current) => ({
            ...current,
            [key]: { ...current[key], status: "failed", error: weight.error },
          }));
          continue;
        }

        setRows((current) => ({ ...current, [key]: { ...current[key], status: "creating" } }));
        let res: VariantCreateResult;
        try {
          res = await createVariant({
            productId: product.id,
            sku: row.sku,
            name: row.name,
            optionValues: combination,
            weightGrams: weight.grams,
            // Only ever true for a product that has none at all — see variant-actions.ts.
            makeDefault: variantCount === 0,
          });
        } catch {
          // A dropped request marks THIS row failed and lets the loop continue, same as
          // a server-side refusal — not an unhandled rejection that strands every row.
          res = { ok: false, error: UNREACHABLE };
        }

        if (res.ok) {
          variantCount += 1;
          setNewVariants((current) => [...current, res.variant as unknown as VariantRow]);
          setRows((current) => ({
            ...current,
            [key]: { ...current[key], status: "created", error: undefined },
          }));
        } else {
          // Left on screen with its message and an editable SKU, and the loop CONTINUES:
          // one collision should not strand the remaining nine rows.
          setRows((current) => ({
            ...current,
            [key]: { ...current[key], status: "failed", error: res.error },
          }));
        }
      }
      setApplying(false);
    });
  };

  /** The simple-product path: the ONE create the SingleVariantForm makes. Empty
   *  option_values and always the default — the form only renders while the product
   *  has no variants at all, so there is nothing to demote. */
  const onCreateSingle = async (input: {
    sku: string;
    name: string;
    weightGrams: number | null;
  }): Promise<VariantCreateResult> => {
    const res = await createVariant({
      productId: product.id,
      sku: input.sku,
      name: input.name,
      optionValues: {},
      weightGrams: input.weightGrams,
      makeDefault: true,
    });
    if (res.ok) {
      setNewVariants((current) => [...current, res.variant as unknown as VariantRow]);
    }
    return res;
  };

  // The axes AS STORED, frozen at load. Renames are the difference between this and
  // `axes`, so it must not be recomputed from `allVariants` — a successful rename updates
  // those, and the offer would vanish mid-loop.
  const [derivedAxes, setDerivedAxes] = useState<Axis[]>(() => deriveAxes(variants));
  const renames = useMemo(() => renameSummary(derivedAxes, axes), [derivedAxes, axes]);
  const mismatched = useMemo(() => nameMismatches(allVariants), [allVariants]);
  const [tidyBusy, setTidyBusy] = useState(false);
  const [tidyError, setTidyError] = useState<string | null>(null);
  const [tidyDone, setTidyDone] = useState<string | null>(null);

  /** One PATCH per variant, reporting the first failure and stopping — a half-applied
   *  rename leaves a product with two names for one axis, which is the mess this exists to
   *  clean up, so it must not be compounded by ploughing on. */
  const runTidy = (
    targets: { id: number; patch: { optionValues?: Record<string, string>; name?: string } }[],
    describe: (n: number) => string,
  ) => {
    setTidyBusy(true);
    setTidyError(null);
    setTidyDone(null);
    startImageTransition(async () => {
      let changed = 0;
      for (const target of targets) {
        let res: VariantCreateResult;
        try {
          res = await updateVariant({ variantId: target.id, ...target.patch });
        } catch {
          res = { ok: false, error: UNREACHABLE };
        }
        if (!res.ok) {
          setTidyError(`${res.error} ${changed} of ${targets.length} were changed.`);
          setTidyBusy(false);
          return;
        }
        changed += 1;
        setNewVariants((current) =>
          current.some((v) => v.id === res.variant.id)
            ? current.map((v) => (v.id === res.variant.id ? (res.variant as unknown as VariantRow) : v))
            : current,
        );
        setUpdated((current) => ({ ...current, [res.variant.id]: res.variant as unknown as VariantRow }));
      }
      setTidyDone(describe(changed));
      setTidyBusy(false);
    });
  };

  const onApplyRenames = () =>
    runTidy(
      allVariants
        .filter((v) => Object.keys(v.option_values ?? {}).length > 0)
        .map((v) => ({
          id: v.id,
          patch: { optionValues: remapOptions(v.option_values, derivedAxes, axes) },
        })),
      (n) => {
        // The stored shape now matches what is on screen, so the offer must clear.
        setDerivedAxes(axes);
        return `Renamed on ${n} ${n === 1 ? "variant" : "variants"}.`;
      },
    );

  const onFixNames = () =>
    runTidy(
      mismatched.map((v) => ({ id: v.id, patch: { name: variantName(v.option_values) } })),
      (n) => `Renamed ${n} ${n === 1 ? "variant" : "variants"}.`,
    );

  // --- variant weights ------------------------------------------------------------
  //
  // Commit-on-blur, exactly like the price grid: nothing is written for an untouched
  // or unchanged field, and each write lands immediately (weights are variant data,
  // not part of the product form's Save). Drafts live here because the panel unmounts
  // on every tab switch.
  const [weightDrafts, setWeightDrafts] = useState<Record<number, string>>({});
  const [weightErrors, setWeightErrors] = useState<Record<number, string>>({});
  const [weightBusyId, setWeightBusyId] = useState<number | null>(null);

  const onWeightDraft = (variantId: number, text: string) => {
    setWeightDrafts((current) => ({ ...current, [variantId]: text }));
    setWeightErrors((current) => {
      if (!current[variantId]) return current;
      const next = { ...current };
      delete next[variantId];
      return next;
    });
  };

  const onWeightCommit = (variantId: number) => {
    const typed = weightDrafts[variantId];
    if (typed === undefined) return;

    const parsed = parseWeightInput(typed);
    if (!parsed.ok) {
      setWeightErrors((current) => ({ ...current, [variantId]: parsed.error }));
      return;
    }
    const stored = allVariants.find((v) => v.id === variantId)?.weight_grams ?? null;
    if (parsed.grams === stored) {
      // Typing the value that was already there is not an edit — no request, no
      // audit row. Clearing the draft puts the cell back on the stored value.
      setWeightDrafts((current) => {
        const next = { ...current };
        delete next[variantId];
        return next;
      });
      return;
    }

    setWeightBusyId(variantId);
    startImageTransition(async () => {
      // The same load-bearing catch as every write in this file: a rejected request
      // must become a message, not an unhandled rejection that unmounts the editor.
      let res: VariantCreateResult;
      try {
        res = await updateVariant({ variantId, weightGrams: parsed.grams });
      } catch {
        res = { ok: false, error: UNREACHABLE };
      }
      setWeightBusyId(null);
      if (!res.ok) {
        setWeightErrors((current) => ({ ...current, [variantId]: res.error }));
        return;
      }
      // Adopt the saved row (same pattern as the rename loop), and drop the draft so
      // the cell renders what the database now holds.
      setUpdated((current) => ({ ...current, [res.variant.id]: res.variant as unknown as VariantRow }));
      setNewVariants((current) =>
        current.some((v) => v.id === res.variant.id)
          ? current.map((v) => (v.id === res.variant.id ? (res.variant as unknown as VariantRow) : v))
          : current,
      );
      setWeightDrafts((current) => {
        const next = { ...current };
        delete next[variantId];
        return next;
      });
    });
  };

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
      let res: AdjustResult;
      try {
        res = await adjustStock({ stockItemId: adjustTarget.id, ...values });
      } catch {
        res = { ok: false, error: UNREACHABLE };
      }
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

  // `allVariants`, NOT the `variants` server prop. The prop only updates on a route
  // refresh, and nothing triggers one any more (the per-cell actions' revalidatePath
  // was what did, at ~13 API requests a call — removed 2026-08-10). Built from the
  // prop, a variant created on the Variants tab this session had NO row here, and the
  // create→price flow ended at an empty grid until a manual reload.
  const grid = useMemo(
    () => buildPriceGrid(allVariants, prices, currencies),
    [allVariants, prices, currencies],
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
      // The same load-bearing catch as `runImageWrite`: a rejected REQUEST (network
      // drop, platform refusal) otherwise skips setBusyCell(null) and unmounts the
      // editor as an unhandled rejection. This path shipped without one and a dropped
      // price write took the whole page down.
      let res: PriceWriteResult;
      try {
        res = await savePrice({
          priceId: cell.price?.id ?? null,
          variantId,
          currency,
          amount: typed.trim(),
          productSlug: baseline.slug,
        });
      } catch {
        res = { ok: false, error: UNREACHABLE };
      }
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
      let next: SaveResult;
      try {
        next = await save(baseline.slug, values);
      } catch {
        next = { errors: { fields: {}, banner: UNREACHABLE } };
      }
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
                : "border-transparent text-muted hover:text-foreground"
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
            {/* Only while there is truly nothing: one variant existing means the path
                was taken (or the product is variable), and a half-built axis means the
                matrix is the intent — showing both invites creating one of each. */}
            {allVariants.length === 0 && axes.length === 0 && (
              <SingleVariantForm
                defaultSku={product.slug}
                defaultName={values.name}
                onCreate={onCreateSingle}
              />
            )}

            <OptionEditor
              axes={axes}
              errors={axisErrors}
              onChange={setAxes}
              hasVariants={allVariants.length > 0}
            />

            <RenamePanel
              summary={renames}
              affectedCount={
                allVariants.filter((v) => Object.keys(v.option_values ?? {}).length > 0).length
              }
              mismatchCount={mismatched.length}
              busy={tidyBusy}
              error={tidyError}
              done={tidyDone}
              onApplyRenames={onApplyRenames}
              onFixNames={onFixNames}
            />

            {axes.length > 0 && (
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={onGenerate}
                  disabled={axisErrors.length > 0 || applying}
                  className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent disabled:opacity-40"
                >
                  Generate variants
                </button>
                {axisErrors.length > 0 && (
                  <span className="text-xs text-muted">Fix the options above first.</span>
                )}
              </div>
            )}

            {preview && (
              <MatrixPreview
                diff={preview.diff}
                rows={rows}
                busy={applying}
                stale={previewStale}
                onSku={(key, sku) =>
                  setRows((current) => ({ ...current, [key]: { ...current[key], sku } }))
                }
                onWeight={(key, weight) =>
                  setRows((current) => ({ ...current, [key]: { ...current[key], weight } }))
                }
                onApply={onApply}
                onRegenerate={onGenerate}
              />
            )}

            <VariantsPanel
              variants={allVariants}
              stock={stockRows}
              warehouses={warehouseColumns(stockRows)}
              onAdjust={openAdjust}
              weightDrafts={weightDrafts}
              weightErrors={weightErrors}
              weightBusyId={weightBusyId}
              onWeightDraft={onWeightDraft}
              onWeightCommit={onWeightCommit}
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
        {tab === "for-who" && (
          <ForWhoPanel values={values} errors={errors} onChange={onChange} />
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
        {tab === "videos" && (
          <VideosPanel
            videos={videos}
            busy={videoBusy}
            progress={videoProgress}
            error={videoError}
            warning={videoWarning}
            onUpload={onVideoUpload}
            onMove={onVideoMove}
            onDelete={onVideoDelete}
          />
        )}
        {tab === "seo" && (
          <SeoPanel values={values} errors={errors} onChange={onChange} siteUrl={siteUrl} />
        )}
      </div>

      <div className="sticky bottom-0 mt-6 flex items-center gap-3 border-t border-line bg-background/95 py-3 backdrop-blur">
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
