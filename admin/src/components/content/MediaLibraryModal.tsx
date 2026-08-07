"use client";

/**
 * The media library picker (2026-08-07).
 *
 * Opened from a media slot in the tile editor, so an image uploaded once can be used on
 * any number of tiles without re-uploading. Picking does NOT write anything — the caller
 * stages the pick exactly like a chosen file, and it applies on Save with everything
 * else. "Upload new" both adds the file to the library and picks it, because that is
 * what somebody opening a picker with a file in hand means.
 *
 * A plain overlay like HomeBannerModal, but WITHOUT its own Escape listener: the parent
 * owns one document-level listener and routes Escape here first while this is open —
 * two listeners on `document` cannot stop each other, so stacking them would close both
 * modals at once.
 */
import { useEffect, useRef, useState, useTransition } from "react";
import { searchMediaAction, uploadMediaAction } from "@/app/(shell)/content/media/actions";
import { downscaleImage } from "@/lib/image";
import type { MediaAssetRow } from "@/lib/media";

export function MediaLibraryModal({
  kind,
  heading,
  onPick,
  onClose,
}: {
  kind: "image" | "video";
  /** e.g. "Image — choose from the library" */
  heading: string;
  onPick: (asset: MediaAssetRow) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<MediaAssetRow[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, startLoading] = useTransition();
  const [uploading, setUploading] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  // Debounced server-side search; page 1 replaces, later pages append.
  useEffect(() => {
    const handle = setTimeout(
      () =>
        startLoading(async () => {
          try {
            const result = await searchMediaAction({ kind, query, page });
            setMessage(result.message ?? null);
            setItems((current) => (page === 1 ? result.items : [...current, ...result.items]));
            setHasMore(result.hasMore);
          } catch {
            setMessage("The library could not be loaded.");
          }
        }),
      query ? 250 : 0,
    );
    return () => clearTimeout(handle);
  }, [kind, query, page]);

  const upload = async (file: File) => {
    setUploading(true);
    setMessage(null);
    try {
      const staged = kind === "video" ? file : await downscaleImage(file);
      const formData = new FormData();
      formData.set("file", staged);
      const result = await uploadMediaAction(formData);
      if (result.asset) onPick(result.asset);
      else setMessage(result.message ?? "The upload was refused — try again.");
    } catch {
      setMessage(
        "The upload did not reach the server. If the file is over about 4 MB, compress it and try again.",
      );
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/40 p-4 sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label={heading}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-2xl rounded-[var(--radius-card)] border border-line bg-background p-5 shadow-lg">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold">{heading}</h2>
            <p className="mt-0.5 text-xs text-muted">
              Everything uploaded before is here — pick one, or upload a new file.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close library"
            className="rounded border border-line px-2 py-0.5 text-sm text-muted hover:border-accent hover:text-fg"
          >
            ✕
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            ref={searchRef}
            type="search"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            placeholder="Search by file name…"
            className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
          />
          <label className="inline-block cursor-pointer rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90">
            {uploading ? "Uploading…" : "Upload new"}
            <input
              type="file"
              accept={kind === "video" ? "video/mp4,video/webm" : "image/*"}
              className="hidden"
              disabled={uploading}
              onChange={(e) => {
                const file = e.currentTarget.files?.[0];
                if (file) void upload(file);
                e.currentTarget.value = "";
              }}
            />
          </label>
        </div>

        {message && (
          <p className="mt-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
            {message}
          </p>
        )}

        {items.length === 0 && !loading ? (
          <p className="mt-4 rounded border border-dashed border-line p-6 text-center text-sm text-muted">
            {query
              ? "Nothing in the library matches that name."
              : `No ${kind}s in the library yet — the first upload starts it.`}
          </p>
        ) : (
          <ul className="mt-4 grid grid-cols-3 gap-3 sm:grid-cols-4">
            {items.map((asset) => (
              <li key={asset.id}>
                <button
                  type="button"
                  onClick={() => onPick(asset)}
                  className="block w-full overflow-hidden rounded border border-line text-left hover:border-accent focus:border-accent focus:outline-none"
                >
                  <span className="block aspect-square bg-surface">
                    {asset.kind === "video" ? (
                      <video
                        src={asset.file}
                        preload="metadata"
                        muted
                        playsInline
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      // eslint-disable-next-line @next/next/no-img-element -- library thumbnail of an uploaded file; next/image buys nothing here.
                      <img src={asset.file} alt="" loading="lazy" className="h-full w-full object-cover" />
                    )}
                  </span>
                  <span className="block truncate px-1.5 py-1 text-[11px] text-muted">
                    {asset.original_name || asset.file.split("/").pop()}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 flex items-center gap-2">
          {hasMore && (
            <button
              type="button"
              onClick={() => setPage((p) => p + 1)}
              disabled={loading}
              className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent disabled:opacity-40"
            >
              {loading ? "Loading…" : "Show more"}
            </button>
          )}
          {loading && !hasMore && <span className="text-xs text-muted">Loading…</span>}
        </div>
      </div>
    </div>
  );
}
