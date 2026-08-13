/**
 * The Images tab: upload, reorder, alt text, delete.
 *
 * ── THIS TAB WRITES IMMEDIATELY, AND SAYS SO ────────────────────────────────────────
 *
 * 17a design decision 1: the product's own fields save on Save; images are a separate API
 * resource and take effect at once. The decision's own words are that the UI must make
 * that obvious rather than hide it — hence the notice at the top. Somebody who deletes an
 * image and then abandons the form without saving has still deleted the image.
 *
 * ── A FAILED UPLOAD MUST NOT COST THE REST OF THE FORM ──────────────────────────────
 *
 * Named in the spec. This comment used to justify "no revalidatePath" with "a refresh
 * would remount the editor and discard unsaved text" — that is mechanically FALSE: a
 * route refresh re-renders Server Components and PRESERVES client component state
 * (the Save action has always revalidated the editor's own path without eating
 * drafts). The real reason image writes don't revalidate is cost: in Next 16 any
 * revalidatePath in a Server Function refreshes the current route too, ~13 API GETs
 * against the per-user throttle per write (see image-actions.ts). Errors are rendered
 * inline and the failed file stays selected so Retry is one click.
 *
 * PRESENTATIONAL-ISH: it owns no product state. The image LIST lives in `ProductEditor`,
 * because this panel unmounts whenever another tab is shown and state here would not
 * survive a tab switch.
 */
import { useRef, useState } from "react";
import type { ProductImage } from "@/app/(shell)/products/[slug]/image-actions";

const GHOST =
  "rounded border border-line px-2 py-1 text-xs text-muted hover:border-accent hover:text-foreground disabled:opacity-40";

export interface ImagesPanelProps {
  images: ProductImage[];
  busy: boolean;
  error: string | null;
  onUpload: (file: File, alt: string) => void;
  onAlt: (id: number, alt: string) => void;
  onMove: (from: number, to: number) => void;
  onDelete: (id: number) => void;
}

export function ImagesPanel({
  images,
  busy,
  error,
  onUpload,
  onAlt,
  onMove,
  onDelete,
}: ImagesPanelProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [alt, setAlt] = useState("");
  // Alt text is edited locally and written on blur, not on every keystroke: a PATCH per
  // character would be dozens of writes and dozens of audit rows for one sentence.
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [confirming, setConfirming] = useState<number | null>(null);

  const submit = () => {
    if (!file) return;
    onUpload(file, alt);
    setFile(null);
    setAlt("");
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <div className="max-w-3xl">
      <p className="rounded-[var(--radius-card)] border border-accent/30 bg-accent/10 p-3 text-sm">
        Changes here take effect <strong>immediately</strong> — they are not part of Save.
      </p>

      {error && (
        <p className="mt-3 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-3 text-sm text-warn">
          {error}
        </p>
      )}

      <div className="mt-4 rounded-[var(--radius-card)] border border-line p-4">
        <div className="grid gap-3 sm:grid-cols-[auto_1fr_auto] sm:items-end">
          <label className="block text-xs text-muted">
            Image file
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="mt-1 block text-sm"
            />
          </label>
          <label className="block text-xs text-muted">
            Alt text
            <input
              type="text"
              value={alt}
              onChange={(e) => setAlt(e.target.value)}
              placeholder="What the photograph shows"
              className="mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
            />
          </label>
          <button
            type="button"
            onClick={submit}
            disabled={!file || busy}
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {busy ? "Working…" : "Upload"}
          </button>
        </div>
      </div>

      {images.length === 0 ? (
        <p className="mt-4 rounded border border-dashed border-line p-6 text-center text-sm text-muted">
          No images yet. The first one is what the storefront leads with.
        </p>
      ) : (
        <ul className="mt-4 space-y-2">
          {images.map((image, index) => (
            <li
              key={image.id}
              className="flex items-center gap-3 rounded-[var(--radius-card)] border border-line p-3"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- admin thumbnail;
                  see ProductTable for why the optimizer is not used here. */}
              <img
                src={image.image}
                alt={image.alt}
                width={56}
                height={56}
                className="h-14 w-14 shrink-0 rounded object-cover"
              />

              <div className="min-w-0 flex-1">
                <input
                  type="text"
                  value={drafts[image.id] ?? image.alt}
                  onChange={(e) => setDrafts({ ...drafts, [image.id]: e.target.value })}
                  onBlur={() => {
                    const next = drafts[image.id];
                    if (next !== undefined && next !== image.alt) onAlt(image.id, next);
                  }}
                  placeholder="Alt text"
                  aria-label={`Alt text for image ${index + 1}`}
                  className="w-full rounded border border-line bg-surface px-2 py-1 text-sm focus:border-accent focus:outline-none"
                />
                {index === 0 && (
                  // Worth stating: the first image is the one the storefront leads with
                  // and the one the products list shows. Ordering is not decoration.
                  <p className="mt-1 text-xs text-muted">Shown first on the storefront.</p>
                )}
              </div>

              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  onClick={() => onMove(index, index - 1)}
                  disabled={index === 0 || busy}
                  aria-label={`Move image ${index + 1} up`}
                  className={GHOST}
                >
                  ↑
                </button>
                <button
                  type="button"
                  onClick={() => onMove(index, index + 1)}
                  disabled={index === images.length - 1 || busy}
                  aria-label={`Move image ${index + 1} down`}
                  className={GHOST}
                >
                  ↓
                </button>

                {confirming === image.id ? (
                  <>
                    {/* Two clicks, because deletion here is immediate and there is no
                        undo — the file is gone from the gallery the moment it lands. */}
                    <button
                      type="button"
                      onClick={() => {
                        setConfirming(null);
                        onDelete(image.id);
                      }}
                      disabled={busy}
                      className="rounded border border-warn/40 bg-warn/10 px-2 py-1 text-xs text-warn"
                    >
                      Really delete
                    </button>
                    <button type="button" onClick={() => setConfirming(null)} className={GHOST}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirming(image.id)}
                    disabled={busy}
                    aria-label={`Delete image ${index + 1}`}
                    className={GHOST}
                  >
                    Delete
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
