"use client";

/**
 * The tile editor modal (Home Content rework, 2026-08-06).
 *
 * Opened FROM a tile, never from a blank form: the caller fixes the placement and the
 * slot, so the editor never asks "where does this go?" — the one question the old
 * placement dropdown forced on every edit. Fields come from the placement spec, labelled
 * the way the storefront tile uses them ("Pill label", not "title").
 *
 * ── EVERYTHING APPLIES ON SAVE, MEDIA INCLUDED ──────────────────────────────────────
 *
 * The old form saved text on Save but pushed media live the moment a file was chosen —
 * two publish moments for one tile, on the shop's front door. Here a chosen file is
 * STAGED (previewed from a local object URL) and uploaded after the text save succeeds,
 * so one Save publishes one coherent tile. On create this also kills the old
 * "save first, then the upload buttons appear" two-step: the action returns the new id
 * and the staged files chase it immediately.
 *
 * A PLAIN OVERLAY, not `<dialog>`, for StockAdjustModal's reason: this renders only
 * while open, so showModal() ceremony buys nothing. Escape and the backdrop close it.
 */
import { startTransition, useEffect, useRef, useState } from "react";
import {
  attachBannerMediaAction,
  clearBannerMediaAction,
  deleteBannerAction,
  saveBannerAction,
  uploadBannerMediaAction,
} from "@/app/(shell)/content/banners/actions";
import { MediaLibraryModal } from "@/components/content/MediaLibraryModal";
import type { BannerField, BannerRow, CountryOption, PlacementSpec } from "@/lib/banners";
import { downscaleImage } from "@/lib/image";
import type { MediaAssetRow } from "@/lib/media";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

type MediaKind = "image" | "mobile_image" | "video";

/** What should happen to one media slot on Save: nothing, replace with `file`, attach
 * the library `asset`, or clear. */
interface MediaDraft {
  file: File | null;
  previewUrl: string | null;
  asset: MediaAssetRow | null;
  remove: boolean;
}

const UNTOUCHED: MediaDraft = { file: null, previewUrl: null, asset: null, remove: false };

/** What a slot holds, for the library modal's heading. */
const SLOT_NOUN: Record<MediaKind, string> = {
  image: "Image",
  mobile_image: "Phone image",
  video: "Video",
};

export function HomeBannerModal({
  spec,
  banner,
  presetSort,
  heading,
  countryOptions,
  onClose,
}: {
  spec: PlacementSpec;
  /** null = creating a new banner for this placement. */
  banner: BannerRow | null;
  /** Where a NEW banner lands in the lineup (existing banners keep their sort). */
  presetSort: number;
  /** e.g. "Shop-by-category · Tile 2" — tells the editor what they clicked. */
  heading: string;
  /** The markets the store sells into, for geo-targeting. Empty list hides the control. */
  countryOptions: CountryOption[];
  onClose: () => void;
}) {
  const [values, setValues] = useState<Record<BannerField, string>>({
    title: banner?.title ?? "",
    subtitle: banner?.subtitle ?? "",
    tagline: banner?.tagline ?? "",
    cta_text: banner?.cta_text ?? "",
    cta_url: banner?.cta_url ?? "",
  });
  const [startsAt, setStartsAt] = useState(banner?.starts_at?.slice(0, 10) ?? "");
  const [endsAt, setEndsAt] = useState(banner?.ends_at?.slice(0, 10) ?? "");
  const [isActive, setIsActive] = useState(banner?.is_active ?? true);
  const [countries, setCountries] = useState<string[]>(banner?.countries ?? []);
  const [media, setMedia] = useState<Record<MediaKind, MediaDraft>>({
    image: UNTOUCHED,
    mobile_image: UNTOUCHED,
    video: UNTOUCHED,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [removeArmed, setRemoveArmed] = useState(false);
  /** Which slot's library picker is open, if any. */
  const [libraryFor, setLibraryFor] = useState<MediaKind | null>(null);
  const firstFieldRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    firstFieldRef.current?.focus();
  }, []);

  useEffect(() => {
    // One document listener owns Escape for both layers: two stacked listeners cannot
    // stop each other, so Escape with the library open would close the whole editor.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (libraryFor) setLibraryFor(null);
      else onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, libraryFor]);

  // Object URLs leak GPU/heap until revoked; one cleanup on unmount covers close,
  // save-and-close and cancel alike.
  const urlsRef = useRef<string[]>([]);
  useEffect(() => {
    const urls = urlsRef.current;
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, []);

  const stageFile = async (kind: MediaKind, file: File | null) => {
    if (!file) return;
    // Images are downscaled BEFORE staging, so the preview shows the file that will
    // actually upload — and so the upload fits the platform's request-body cap.
    const staged = kind === "video" ? file : await downscaleImage(file);
    const previewUrl = URL.createObjectURL(staged);
    urlsRef.current.push(previewUrl);
    setMedia((m) => ({ ...m, [kind]: { file: staged, previewUrl, asset: null, remove: false } }));
  };

  /** A library pick — previewed straight from its hosted URL, applied on Save. */
  const stageAsset = (kind: MediaKind, asset: MediaAssetRow) => {
    setMedia((m) => ({ ...m, [kind]: { file: null, previewUrl: asset.file, asset, remove: false } }));
    setLibraryFor(null);
  };

  const stageRemove = (kind: MediaKind) => {
    setMedia((m) => ({ ...m, [kind]: { file: null, previewUrl: null, asset: null, remove: true } }));
  };

  const unstage = (kind: MediaKind) => {
    setMedia((m) => ({ ...m, [kind]: UNTOUCHED }));
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      // The try/catch is load-bearing: a server action whose REQUEST is rejected (a
      // body over the size limit, a network drop) rejects the promise on the client —
      // without the catch, `pending` stays true and the modal says "Saving…" forever.
      try {
        const state = await saveBannerAction({
          id: banner?.id,
          title: values.title,
          subtitle: values.subtitle,
          tagline: values.tagline,
          cta_text: values.cta_text,
          cta_url: values.cta_url,
          placement: spec.value,
          sort: banner?.sort ?? presetSort,
          starts_at: startsAt,
          ends_at: endsAt,
          is_active: isActive,
          countries,
        });
        if (!state.savedAt || !state.id) {
          setPending(false);
          setErrors(state.fieldErrors ?? {});
          setMessage(state.message ?? null);
          return;
        }
        // Text is saved; now let the staged media chase the id. A failed upload keeps the
        // modal open and says so — the tile exists, its artwork just has not changed.
        for (const kind of ["image", "mobile_image", "video"] as MediaKind[]) {
          const draft = media[kind];
          let result = null;
          if (draft.file) {
            const formData = new FormData();
            formData.set("file", draft.file);
            result = await uploadBannerMediaAction(state.id, kind, formData);
          } else if (draft.asset) {
            result = await attachBannerMediaAction(state.id, kind, draft.asset.id);
          } else if (draft.remove) {
            result = await clearBannerMediaAction(state.id, kind);
          }
          if (result && !result.savedAt) {
            const noun = kind === "video" ? "video" : kind === "mobile_image" ? "phone image" : "image";
            setPending(false);
            setMessage(
              `Saved, but the ${noun} did not go through: ${result.message ?? "try the upload again."}`,
            );
            return;
          }
        }
        setPending(false);
        onClose();
      } catch {
        setPending(false);
        setMessage(
          "The save did not reach the server. If you attached a large file (over about 4 MB), compress it and try again — otherwise check the connection and retry.",
        );
      }
    });
  };

  const remove = () => {
    if (!banner) return;
    if (!removeArmed) {
      setRemoveArmed(true);
      return;
    }
    setPending(true);
    startTransition(async () => {
      try {
        const state = await deleteBannerAction(banner.id);
        setPending(false);
        if (state.savedAt) onClose();
        else setMessage(state.message ?? "That could not be removed.");
      } catch {
        setPending(false);
        setMessage("The removal did not reach the server — check the connection and retry.");
      }
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={heading}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        onSubmit={submit}
        className="w-full max-w-xl rounded-[var(--radius-card)] border border-line bg-background p-5 shadow-lg"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold">{heading}</h2>
            <p className="mt-0.5 text-xs text-muted">{spec.guide}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded border border-line px-2 py-0.5 text-sm text-muted hover:border-accent hover:text-fg"
          >
            ✕
          </button>
        </div>

        {message && (
          <p className="mt-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
            {message}
          </p>
        )}

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {spec.fields.map((field, i) => (
            <label
              key={field.key}
              className={`block text-xs text-muted ${field.key === "tagline" || field.key === "title" ? "sm:col-span-2" : ""}`}
            >
              {field.label}
              <input
                ref={i === 0 ? firstFieldRef : undefined}
                type="text"
                value={values[field.key]}
                onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
                className={`mt-1 ${FIELD}`}
              />
              {field.hint && <span className="mt-1 block text-[11px] text-muted">{field.hint}</span>}
              {errors[field.key] && <p className="mt-1 text-xs text-warn">{errors[field.key]}</p>}
            </label>
          ))}
        </div>

        {spec.media && (
          <div className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
            <MediaSlot
              label="Image"
              kind="image"
              accept="image/*"
              current={banner?.image ?? null}
              draft={media.image}
              aspect={spec.aspect}
              onPick={(f) => stageFile("image", f)}
              onLibrary={() => setLibraryFor("image")}
              onRemove={() => stageRemove("image")}
              onUndo={() => unstage("image")}
            />
            <MediaSlot
              label={spec.value === "hero" ? "Video (the image becomes its poster)" : "Video (optional — plays instead of the image)"}
              kind="video"
              accept="video/mp4,video/webm"
              current={banner?.video ?? null}
              draft={media.video}
              aspect={spec.aspect}
              onPick={(f) => stageFile("video", f)}
              onLibrary={() => setLibraryFor("video")}
              onRemove={() => stageRemove("video")}
              onUndo={() => unstage("video")}
            />
            <MediaSlot
              label="Phone image (optional — small screens show it instead of the image)"
              kind="mobile_image"
              accept="image/*"
              current={banner?.mobile_image ?? null}
              draft={media.mobile_image}
              aspect={spec.aspect}
              onPick={(f) => stageFile("mobile_image", f)}
              onLibrary={() => setLibraryFor("mobile_image")}
              onRemove={() => stageRemove("mobile_image")}
              onUndo={() => unstage("mobile_image")}
            />
          </div>
        )}

        <div className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-3">
          <label className="block text-xs text-muted">
            Starts
            <input type="date" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} className={`mt-1 ${FIELD}`} />
          </label>
          <label className="block text-xs text-muted">
            Ends
            <input type="date" value={endsAt} onChange={(e) => setEndsAt(e.target.value)} className={`mt-1 ${FIELD}`} />
            {errors.ends_at && <p className="mt-1 text-xs text-warn">{errors.ends_at}</p>}
          </label>
          <label className="flex items-end gap-2 pb-1 text-sm">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="h-4 w-4 rounded border-line"
            />
            Switched on
          </label>
        </div>
        <p className="mt-2 text-[11px] text-muted">
          Leave the dates empty to show always. Scheduling is enforced on the server — a
          tile never appears before its start.
        </p>

        {countryOptions.length > 0 && (
          <div className="mt-4 border-t border-line pt-4">
            <p className="text-xs font-medium text-muted">
              Countries — tick none to show everywhere
            </p>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
              {countryOptions.map((c) => (
                <label key={c.code} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={countries.includes(c.code)}
                    onChange={(e) =>
                      setCountries((prev) =>
                        e.target.checked
                          ? [...prev, c.code]
                          : prev.filter((code) => code !== c.code),
                      )
                    }
                    className="h-4 w-4 rounded border-line"
                  />
                  {c.name}
                </label>
              ))}
            </div>
            {countries.length > 0 && (
              <p className="mt-1.5 text-[11px] text-muted">
                Visitors outside the ticked countries will not see this tile.
              </p>
            )}
          </div>
        )}

        <div className="mt-4 flex items-center gap-2">
          <button
            type="submit"
            disabled={pending}
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {pending ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
          >
            Cancel
          </button>
          {banner && (
            <button
              type="button"
              onClick={remove}
              disabled={pending}
              className={`ml-auto rounded border px-3 py-1.5 text-sm disabled:opacity-40 ${
                removeArmed
                  ? "border-warn bg-warn/10 text-warn"
                  : "border-line text-muted hover:border-warn hover:text-warn"
              }`}
            >
              {removeArmed ? "Really remove?" : "Remove"}
            </button>
          )}
        </div>
      </form>

      {libraryFor && (
        <MediaLibraryModal
          kind={libraryFor === "video" ? "video" : "image"}
          heading={`${SLOT_NOUN[libraryFor]} — choose from the library`}
          onPick={(asset) => stageAsset(libraryFor, asset)}
          onClose={() => setLibraryFor(null)}
        />
      )}
    </div>
  );
}

/**
 * One staged media slot. The preview shows the staged pick (a chosen file's object URL
 * or a library asset's hosted URL), else the current upload, else empty. "Library"
 * opens the picker so an earlier upload can be reused; "Remove" stages a clear; "Undo"
 * walks any staging back.
 */
function MediaSlot({
  label,
  kind,
  accept,
  current,
  draft,
  aspect,
  onPick,
  onLibrary,
  onRemove,
  onUndo,
}: {
  label: string;
  kind: MediaKind;
  accept: string;
  current: string | null;
  draft: MediaDraft;
  aspect: string;
  onPick: (file: File) => void;
  onLibrary: () => void;
  onRemove: () => void;
  onUndo: () => void;
}) {
  const showUrl = draft.previewUrl ?? (draft.remove ? null : current);
  const staged = draft.file !== null || draft.asset !== null || draft.remove;
  return (
    <div className="text-xs">
      <p className="font-medium text-muted">{label}</p>
      <div
        className={`mt-1.5 overflow-hidden rounded border border-line bg-surface ${aspect || "aspect-video"}`}
      >
        {showUrl ? (
          kind === "video" ? (
            <video src={showUrl} preload="metadata" muted playsInline className="h-full w-full object-cover" />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element -- admin thumbnail of an uploaded/staged file; next/image buys nothing here.
            <img src={showUrl} alt="" className="h-full w-full object-cover" />
          )
        ) : (
          <div className="grid h-full w-full place-items-center text-muted">
            {draft.remove ? "will be removed" : "none yet"}
          </div>
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        <label className="inline-block cursor-pointer rounded border border-line px-2.5 py-1 hover:border-accent">
          {showUrl ? "Replace" : "Choose file"}
          <input
            type="file"
            accept={accept}
            className="hidden"
            onChange={(e) => {
              const file = e.currentTarget.files?.[0];
              if (file) onPick(file);
              e.currentTarget.value = "";
            }}
          />
        </label>
        <button
          type="button"
          onClick={onLibrary}
          className="rounded border border-line px-2.5 py-1 hover:border-accent"
        >
          Library
        </button>
        {staged ? (
          <button type="button" onClick={onUndo} className="rounded border border-line px-2.5 py-1 hover:border-accent">
            Undo
          </button>
        ) : (
          current && (
            <button
              type="button"
              onClick={onRemove}
              className="rounded border border-line px-2.5 py-1 text-muted hover:border-warn hover:text-warn"
            >
              Remove
            </button>
          )
        )}
      </div>
      {staged && <p className="mt-1 text-[11px] text-muted">Applies when you press Save.</p>}
    </div>
  );
}
