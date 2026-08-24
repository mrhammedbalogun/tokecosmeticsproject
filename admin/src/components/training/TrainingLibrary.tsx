"use client";

/**
 * The training library's grid, player, and (for the Owner) the editor (2026-08-23).
 *
 * ── CLICK-TO-PLAY, NOT AUTOLOADED IFRAMES ───────────────────────────────────────────
 *
 * A library of N videos rendered as N live YouTube iframes downloads N players before
 * anybody watches anything. Each card is therefore a poster (`i.ytimg.com`, built from
 * the validated video id) with a play button, and the iframe exists only after the
 * click — at which point `autoplay=1` makes that click the play action. One video
 * plays at a time: starting a second one replaces the first, because two overlapping
 * voice-overs is never what anyone meant.
 *
 * ── THE OWNER'S CONTROLS RENDER ONLY FOR THE OWNER ──────────────────────────────────
 *
 * `canManage` comes from admin-me's scopes, server-side. Hiding the buttons is
 * ergonomics; every action lands on `training.manage` endpoints that decide for
 * themselves. Delete asks twice inline (the codebase's two-step confirm); hide/show is
 * one click because it is instantly reversible in the same row.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  deleteTrainingAction,
  saveTrainingAction,
  setTrainingPublishedAction,
  type TrainingActionState,
  type TrainingInput,
} from "@/app/(shell)/training/actions";
import {
  parseYoutubeVideoId,
  trainingEmbedUrl,
  trainingThumbnailUrl,
  type TrainingRow,
} from "@/lib/training";

const FIELD =
  "mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function TrainingLibrary({
  rows,
  canManage,
}: {
  rows: TrainingRow[];
  canManage: boolean;
}) {
  const router = useRouter();
  // `null` = closed, `"new"` = the create form, a number = editing that row.
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [playing, setPlaying] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  /** Every row action funnels through here so a failure reaches the operator as a
   *  sentence instead of vanishing into a rejected promise. */
  async function run(action: () => Promise<TrainingActionState>) {
    setMessage(null);
    const result = await action();
    if (result.message) {
      setMessage(result.message);
    } else if (result.fieldErrors) {
      // Row buttons send one safe field; a fielded error back means the row changed
      // under us. Surface the first sentence rather than nothing.
      setMessage(Object.values(result.fieldErrors)[0] ?? "That change was refused.");
    } else {
      setConfirming(null);
      startTransition(() => router.refresh());
    }
  }

  return (
    <div>
      {canManage && (
        <div className="mb-4 flex items-center justify-end">
          {editing !== "new" && (
            <button
              type="button"
              onClick={() => setEditing("new")}
              className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
            >
              Add training
            </button>
          )}
        </div>
      )}

      {editing === "new" && (
        <div className="mb-4">
          <TrainingForm
            row={null}
            onDone={() => setEditing(null)}
            onCancel={() => setEditing(null)}
          />
        </div>
      )}

      {message && (
        <p
          role="alert"
          className="mb-4 rounded border border-danger/30 bg-danger/5 p-3 text-sm text-danger"
        >
          {message}
        </p>
      )}

      {rows.length === 0 ? (
        <p className="rounded-[var(--radius-card)] border border-line bg-surface p-6 text-center text-sm text-muted">
          {canManage
            ? "No trainings yet. Add the first one — a title, what it covers, and the YouTube link."
            : "No trainings have been published yet. Check back soon."}
        </p>
      ) : (
        <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((row) => (
            <li
              key={row.id}
              className="flex flex-col overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface"
            >
              {/* ── the player ─────────────────────────────────────────────── */}
              <div className="relative aspect-video w-full bg-black">
                {playing === row.id ? (
                  <iframe
                    src={trainingEmbedUrl(row.video_id)}
                    title={row.title}
                    className="absolute inset-0 h-full w-full"
                    allow="autoplay; encrypted-media; fullscreen; picture-in-picture"
                    allowFullScreen
                    // The admin ships `Referrer-Policy: no-referrer` site-wide
                    // (next.config.ts) so customer IDs never leak into third-party
                    // referers. YouTube, however, REQUIRES a referer on embeds since
                    // 2025 and refuses to play without one ("Error 153 — video player
                    // configuration error"). This per-element override wins over the
                    // document policy for this one request and sends ONLY our origin —
                    // no path, so nothing sensitive — which is exactly what YouTube
                    // needs to verify the embed.
                    referrerPolicy="strict-origin-when-cross-origin"
                  />
                ) : (
                  <button
                    type="button"
                    onClick={() => setPlaying(row.id)}
                    className="group absolute inset-0 h-full w-full"
                    aria-label={`Play “${row.title}”`}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element -- a fixed
                        YouTube CDN still; next/image would proxy it through our own
                        origin for no benefit and needs a remotePatterns entry. */}
                    <img
                      src={trainingThumbnailUrl(row.video_id)}
                      alt=""
                      loading="lazy"
                      className="absolute inset-0 h-full w-full object-cover opacity-90 transition-opacity group-hover:opacity-100"
                    />
                    <span className="absolute inset-0 flex items-center justify-center">
                      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-black/70 text-white transition-transform group-hover:scale-110">
                        {/* A play triangle, drawn — no icon dependency. */}
                        <svg viewBox="0 0 24 24" className="ml-1 h-6 w-6 fill-current" aria-hidden>
                          <path d="M8 5v14l11-7z" />
                        </svg>
                      </span>
                    </span>
                  </button>
                )}
              </div>

              {/* ── the words ──────────────────────────────────────────────── */}
              <div className="flex flex-1 flex-col p-4">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="font-medium">{row.title}</h2>
                  {canManage && row.is_published === false && (
                    <span className="shrink-0 rounded-full border border-warn/30 bg-warn/5 px-2 py-0.5 text-[11px] text-warn">
                      Hidden from staff
                    </span>
                  )}
                </div>
                {row.description && (
                  // Plain text with the author's line breaks kept. NEVER HTML.
                  <p className="mt-1 whitespace-pre-line text-sm text-muted">
                    {row.description}
                  </p>
                )}
                <div className="mt-auto flex flex-wrap items-center gap-3 pt-3 text-xs">
                  <a
                    href={row.youtube_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-muted underline-offset-2 hover:underline"
                  >
                    Open on YouTube
                  </a>
                  {canManage && (
                    <span className="ml-auto flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setEditing(row.id)}
                        className="rounded border border-line px-2 py-1 hover:bg-surface"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          run(() =>
                            setTrainingPublishedAction(row.id, row.is_published === false),
                          )
                        }
                        className="rounded border border-line px-2 py-1 hover:bg-surface"
                      >
                        {row.is_published === false ? "Publish" : "Hide"}
                      </button>
                      {confirming === row.id ? (
                        <>
                          <button
                            type="button"
                            onClick={() => run(() => deleteTrainingAction(row.id))}
                            className="rounded bg-danger px-2 py-1 font-medium text-white hover:opacity-90"
                          >
                            Delete for good
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirming(null)}
                            className="rounded border border-line px-2 py-1 hover:bg-surface"
                          >
                            Keep
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setConfirming(row.id)}
                          className="rounded border border-danger/40 px-2 py-1 text-danger hover:bg-danger/5"
                        >
                          Delete
                        </button>
                      )}
                    </span>
                  )}
                </div>
                {editing === row.id && (
                  <div className="mt-3">
                    <TrainingForm
                      row={row}
                      onDone={() => setEditing(null)}
                      onCancel={() => setEditing(null)}
                    />
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── the Owner's form ──────────────────────────────────────────────────────────────

type Draft = Omit<TrainingInput, "id">;

const EMPTY: Draft = {
  title: "",
  description: "",
  youtube_url: "",
  position: 0,
  is_published: true,
};

function TrainingForm({
  row,
  onDone,
  onCancel,
}: {
  /** null = create. */
  row: TrainingRow | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState<Draft>(
    row
      ? {
          title: row.title,
          description: row.description,
          youtube_url: row.youtube_url,
          position: row.position,
          is_published: row.is_published !== false,
        }
      : EMPTY,
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Instant preview from the client-side mirror parser — feedback while typing. The
  // backend re-parses from scratch and its verdict is the one the form must render.
  const previewId = parseYoutubeVideoId(draft.youtube_url);

  async function submit() {
    setSaving(true);
    setErrors({});
    setMessage(null);
    const result = await saveTrainingAction({ id: row?.id ?? null, ...draft });
    setSaving(false);
    if (result.fieldErrors) setErrors(result.fieldErrors);
    else if (result.message) setMessage(result.message);
    else {
      onDone();
      router.refresh();
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      className="rounded-[var(--radius-card)] border border-line bg-surface p-4"
    >
      <p className="text-sm font-medium">{row ? "Edit training" : "Add training"}</p>

      {message && (
        <p role="alert" className="mt-3 rounded border border-danger/30 bg-danger/5 p-3 text-sm text-danger">
          {message}
        </p>
      )}

      <div className="mt-3 grid grid-cols-1 gap-3">
        <label className="block text-sm">
          <span className="text-muted">Title</span>
          <input
            type="text"
            value={draft.title}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            maxLength={200}
            className={FIELD}
            placeholder="e.g. Packing an order for delivery"
          />
          {errors.title && <span className="mt-1 block text-xs text-danger">{errors.title}</span>}
        </label>

        <label className="block text-sm">
          <span className="text-muted">Description</span>
          <textarea
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            rows={3}
            className={FIELD}
            placeholder="What this covers and who should watch it."
          />
          {errors.description && (
            <span className="mt-1 block text-xs text-danger">{errors.description}</span>
          )}
        </label>

        <label className="block text-sm">
          <span className="text-muted">YouTube link</span>
          <input
            type="text"
            value={draft.youtube_url}
            onChange={(e) => setDraft({ ...draft, youtube_url: e.target.value })}
            className={FIELD}
            placeholder="https://www.youtube.com/watch?v=… or https://youtu.be/…"
          />
          {errors.youtube_url ? (
            <span className="mt-1 block text-xs text-danger">{errors.youtube_url}</span>
          ) : draft.youtube_url.trim() && !previewId ? (
            <span className="mt-1 block text-xs text-warn">
              That does not look like the link of one YouTube video yet.
            </span>
          ) : null}
        </label>

        {previewId && (
          <div className="flex items-center gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element -- see the grid. */}
            <img
              src={trainingThumbnailUrl(previewId)}
              alt=""
              className="h-16 w-28 rounded border border-line object-cover"
            />
            <p className="text-xs text-muted">
              This is the video the link points at. Wrong one? Re-copy the link from
              YouTube&apos;s address bar.
            </p>
          </div>
        )}

        <div className="flex flex-wrap items-end gap-4">
          <label className="block text-sm">
            <span className="text-muted">Order in the list</span>
            <input
              type="number"
              min={0}
              value={draft.position}
              onChange={(e) =>
                setDraft({ ...draft, position: Math.max(0, Number(e.target.value) || 0) })
              }
              className={`${FIELD} w-28`}
            />
            {errors.position && (
              <span className="mt-1 block text-xs text-danger">{errors.position}</span>
            )}
          </label>
          <label className="flex items-center gap-2 pb-2 text-sm">
            <input
              type="checkbox"
              checked={draft.is_published}
              onChange={(e) => setDraft({ ...draft, is_published: e.target.checked })}
            />
            <span>
              Published{" "}
              <span className="text-xs text-muted">— staff can see it. Untick to draft.</span>
            </span>
          </label>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {saving ? "Saving…" : row ? "Save changes" : "Add training"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-line px-3 py-1.5 text-sm hover:bg-surface"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
