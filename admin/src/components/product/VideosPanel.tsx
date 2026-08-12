/**
 * The Videos tab: upload (straight to S3), reorder, delete.
 *
 * Same contract as ImagesPanel: writes take effect IMMEDIATELY (they are their own API
 * resource, not part of Save), errors render inline, and the panel owns NO list state —
 * that lives in `ProductEditor`, because this panel unmounts on every tab switch.
 *
 * The upload differs from images in one structural way: the file goes browser → S3 via
 * a presigned ticket (lib/upload.ts), because Vercel kills request bodies over ~4.5MB
 * at its edge and no video fits under that. Hence the progress bar — a 100MB file on a
 * slow uplink takes minutes, and progress-less minutes read as "it has frozen".
 */
import { useRef, useState } from "react";
import type { ProductVideo } from "@/app/(shell)/products/[slug]/video-actions";
import { fileSizeMb } from "@/lib/video";

const GHOST =
  "rounded border border-line px-2 py-1 text-xs text-muted hover:border-accent hover:text-fg disabled:opacity-40";

export interface VideosPanelProps {
  videos: ProductVideo[];
  busy: boolean;
  /** Upload percentage while the S3 leg is in flight, else null. */
  progress: number | null;
  error: string | null;
  /** Non-fatal advice from the server (e.g. "not faststart-encoded"). */
  warning: string | null;
  onUpload: (file: File) => void;
  onMove: (from: number, to: number) => void;
  onDelete: (id: number) => void;
}

export function VideosPanel({
  videos,
  busy,
  progress,
  error,
  warning,
  onUpload,
  onMove,
  onDelete,
}: VideosPanelProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);

  const submit = () => {
    if (!file) return;
    onUpload(file);
    setFile(null);
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
      {warning && (
        <p className="mt-3 rounded-[var(--radius-card)] border border-line bg-surface p-3 text-sm text-muted">
          The video was attached, but: {warning}
        </p>
      )}

      <div className="mt-4 rounded-[var(--radius-card)] border border-line p-4">
        <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <label className="block text-xs text-muted">
            Video file (mp4 or webm, up to 128 MB)
            <input
              ref={fileRef}
              type="file"
              accept="video/mp4,video/webm"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="mt-1 block text-sm"
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
        {file && !busy && (
          <p className="mt-2 text-xs text-muted">
            {file.name} · {fileSizeMb(file)}
          </p>
        )}
        {progress !== null && (
          <div className="mt-3">
            <div
              role="progressbar"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Upload progress"
              className="h-2 overflow-hidden rounded bg-surface"
            >
              <div className="h-full bg-accent transition-[width]" style={{ width: `${progress}%` }} />
            </div>
            <p className="mt-1 text-xs text-muted">Uploading… {progress}%</p>
          </div>
        )}
      </div>

      {videos.length === 0 ? (
        <p className="mt-4 rounded border border-dashed border-line p-6 text-center text-sm text-muted">
          No videos yet. They show under the photo gallery on the product page.
        </p>
      ) : (
        <ul className="mt-4 space-y-2">
          {videos.map((video, index) => (
            <li
              key={video.id}
              className="flex items-center gap-3 rounded-[var(--radius-card)] border border-line p-3"
            >
              {/* preload="metadata" keeps this to a small ranged request; controls so a
                  just-uploaded file can be sanity-watched right here. */}
              <video
                src={video.file}
                preload="metadata"
                controls
                className="h-20 w-32 shrink-0 rounded bg-black/5 object-contain"
              />

              <div className="min-w-0 flex-1 text-sm text-muted">
                <p className="truncate">{video.file.split("/").pop()}</p>
                {index === 0 && <p className="mt-1 text-xs">Shown first on the storefront.</p>}
              </div>

              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  onClick={() => onMove(index, index - 1)}
                  disabled={index === 0 || busy}
                  aria-label={`Move video ${index + 1} up`}
                  className={GHOST}
                >
                  ↑
                </button>
                <button
                  type="button"
                  onClick={() => onMove(index, index + 1)}
                  disabled={index === videos.length - 1 || busy}
                  aria-label={`Move video ${index + 1} down`}
                  className={GHOST}
                >
                  ↓
                </button>

                {confirming === video.id ? (
                  <>
                    {/* Two clicks, like images: removal is immediate and has no undo.
                        (The FILE survives in the media library; only the product
                        binding is deleted.) */}
                    <button
                      type="button"
                      onClick={() => {
                        setConfirming(null);
                        onDelete(video.id);
                      }}
                      disabled={busy}
                      className="rounded border border-warn/40 bg-warn/10 px-2 py-1 text-xs text-warn"
                    >
                      Really remove
                    </button>
                    <button type="button" onClick={() => setConfirming(null)} className={GHOST}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirming(video.id)}
                    disabled={busy}
                    aria-label={`Remove video ${index + 1}`}
                    className={GHOST}
                  >
                    Remove
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
