"use client";

/**
 * Banners (Plan-19c) — the surface the master spec's own checkpoint tests: "change the
 * hero banner and see it live".
 *
 * ── THE LIST ANSWERS "IS IT SHOWING?", NOT "IS IT TICKED?" ──────────────────────────
 *
 * A banner can be active and invisible in three different ways: it starts on Friday, it
 * ended last week, or it is switched off. Those are the same checkbox and completely
 * different situations for somebody who has just emailed a campaign to a mailing list.
 * `bannerState` names which one.
 *
 * The backend enforces the same rule for real — `Banner.is_live` filters the public
 * payload, so a scheduled banner never reaches a browser early. This is a mirror for the
 * operator, not the control.
 */
import { startTransition, useState } from "react";
import { deleteBannerAction, saveBannerAction, uploadBannerMediaAction } from "@/app/(shell)/content/banners/actions";
import { PLACEMENTS, bannerState, type BannerRow } from "@/lib/banners";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

const STATE_STYLES: Record<string, string> = {
  live: "border-ok/50 text-ok",
  scheduled: "border-accent/50 text-accent",
  ended: "border-line text-muted",
  off: "border-line text-muted",
};

export function BannerManager({ banners }: { banners: BannerRow[] }) {
  const [editing, setEditing] = useState<BannerRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const remove = (banner: BannerRow) => {
    setBusy(banner.id);
    setMessage(null);
    startTransition(async () => {
      const state = await deleteBannerAction(banner.id);
      setBusy(null);
      setMessage(state.message ?? null);
    });
  };

  return (
    <div className="space-y-6">
      {message && (
        <p className="rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
          {message}
        </p>
      )}

      {!creating && !editing && (
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >
          New banner
        </button>
      )}

      {(creating || editing) && (
        <BannerForm
          banner={editing}
          onDone={() => {
            setCreating(false);
            setEditing(null);
          }}
        />
      )}

      {banners.length === 0 ? (
        <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
          No banners yet. The shop falls back to its built-in announcements and hero.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
          <table className="w-full min-w-[40rem] text-sm">
            <thead className="bg-surface text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Banner</th>
                <th className="px-3 py-2 text-left font-medium">Where</th>
                <th className="px-3 py-2 text-left font-medium">When</th>
                <th className="px-3 py-2 text-left font-medium">Showing</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {banners.map((banner) => {
                const state = bannerState(banner);
                return (
                  <tr key={banner.id} className="border-t border-line">
                    <td className="px-3 py-2">
                      <div>{banner.title}</div>
                      {banner.subtitle && (
                        <div className="text-xs text-muted">{banner.subtitle}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">{banner.placement}</td>
                    <td className="px-3 py-2 text-xs text-muted">
                      {banner.starts_at || banner.ends_at
                        ? `${banner.starts_at?.slice(0, 10) ?? "…"} → ${banner.ends_at?.slice(0, 10) ?? "…"}`
                        : "always"}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded-full border px-2 py-0.5 text-xs ${STATE_STYLES[state]}`}
                      >
                        {state}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => setEditing(banner)}
                        className="rounded border border-line px-2 py-1 text-xs hover:border-accent"
                      >
                        Edit
                      </button>{" "}
                      <button
                        type="button"
                        onClick={() => remove(banner)}
                        disabled={busy === banner.id}
                        className="rounded border border-line px-2 py-1 text-xs text-muted hover:border-warn hover:text-warn disabled:opacity-40"
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function BannerForm({ banner, onDone }: { banner: BannerRow | null; onDone: () => void }) {
  const [title, setTitle] = useState(banner?.title ?? "");
  const [subtitle, setSubtitle] = useState(banner?.subtitle ?? "");
  const [tagline, setTagline] = useState(banner?.tagline ?? "");
  const [ctaText, setCtaText] = useState(banner?.cta_text ?? "");
  const [ctaUrl, setCtaUrl] = useState(banner?.cta_url ?? "");
  const [placement, setPlacement] = useState<BannerRow["placement"]>(
    banner?.placement ?? "strip",
  );
  const [startsAt, setStartsAt] = useState(banner?.starts_at?.slice(0, 10) ?? "");
  const [endsAt, setEndsAt] = useState(banner?.ends_at?.slice(0, 10) ?? "");
  const [isActive, setIsActive] = useState(banner?.is_active ?? true);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await saveBannerAction({
        id: banner?.id,
        title, subtitle, tagline, cta_text: ctaText, cta_url: ctaUrl, placement,
        starts_at: startsAt, ends_at: endsAt, is_active: isActive,
      });
      setPending(false);
      if (state.savedAt) onDone();
      else {
        setErrors(state.fieldErrors ?? {});
        setMessage(state.message ?? null);
      }
    });
  };

  return (
    <form onSubmit={submit} className="rounded-[var(--radius-card)] border border-line p-4">
      <h2 className="text-sm font-semibold">{banner ? "Edit banner" : "New banner"}</h2>
      {message && (
        <p className="mt-2 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
          {message}
        </p>
      )}
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block text-xs text-muted">
          Title
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} className={`mt-1 ${FIELD}`} />
          <span className="mt-1 block text-xs text-muted">
            On an announcement strip this is the message itself.
          </span>
          {errors.title && <p className="mt-1 text-xs text-warn">{errors.title}</p>}
        </label>
        <label className="block text-xs text-muted">
          Subtitle / eyebrow
          <input type="text" value={subtitle} onChange={(e) => setSubtitle(e.target.value)} className={`mt-1 ${FIELD}`} />
        </label>
        <label className="block text-xs text-muted">
          Tagline (the small paragraph, where the tile shows one)
          <input type="text" value={tagline} onChange={(e) => setTagline(e.target.value)} className={`mt-1 ${FIELD}`} />
        </label>
        <label className="block text-xs text-muted">
          Placement
          <select
            value={placement}
            onChange={(e) => setPlacement(e.target.value)}
            className={`mt-1 ${FIELD}`}
          >
            {PLACEMENTS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
          {/* The uploader's cheat-sheet: what this placement shows and the artwork
              size it wants. */}
          <p className="mt-1 text-[11px] leading-relaxed text-muted">
            {PLACEMENTS.find((p) => p.value === placement)?.guide}
          </p>
        </label>
        <label className="flex items-end gap-2 text-sm">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            className="mb-2 h-4 w-4 rounded border-line"
          />
          <span className="mb-1.5">Switched on</span>
        </label>
        <label className="block text-xs text-muted">
          Starts
          <input type="date" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} className={`mt-1 ${FIELD}`} />
        </label>
        <label className="block text-xs text-muted">
          Ends
          <input type="date" value={endsAt} onChange={(e) => setEndsAt(e.target.value)} className={`mt-1 ${FIELD}`} />
          {errors.ends_at && <p className="mt-1 text-xs text-warn">{errors.ends_at}</p>}
        </label>
        <label className="block text-xs text-muted">
          Button text
          <input type="text" value={ctaText} onChange={(e) => setCtaText(e.target.value)} className={`mt-1 ${FIELD}`} />
        </label>
        <label className="block text-xs text-muted">
          Button link
          <input type="text" value={ctaUrl} onChange={(e) => setCtaUrl(e.target.value)} placeholder="/products" className={`mt-1 ${FIELD}`} />
        </label>
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Saving…" : "Save banner"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
        >
          Cancel
        </button>
      </div>
      {banner && (
        <div className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-3">
          <MediaPicker banner={banner} kind="image" label="Image" accept="image/*" current={banner.image} />
          <MediaPicker banner={banner} kind="mobile_image" label="Mobile image" accept="image/*" current={banner.mobile_image} />
          <MediaPicker banner={banner} kind="video" label="Video (hero slides)" accept="video/mp4,video/webm" current={banner.video} />
        </div>
      )}
      {!banner && (
        <p className="mt-2 text-xs text-muted">
          Save the banner first, then upload its image or video — media attaches to a
          saved banner and goes live immediately.
        </p>
      )}
    </form>
  );
}


/** One upload slot. Media takes effect IMMEDIATELY (unlike the text fields), which the
 * copy says out loud — on the hero this is the shop's front door. Files land in the
 * Toke S3 bucket via the backend. */
function MediaPicker({
  banner,
  kind,
  label,
  accept,
  current,
}: {
  banner: BannerRow;
  kind: "image" | "mobile_image" | "video";
  label: string;
  accept: string;
  current: string | null;
}) {
  const [note, setNote] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  return (
    <div className="text-xs">
      <p className="font-medium">{label}</p>
      <p className="mt-0.5 truncate text-muted">
        {current ? current.split("/").pop() : "none yet"}
      </p>
      <label className="mt-1.5 inline-block cursor-pointer rounded border border-line px-2.5 py-1 hover:border-accent">
        {uploading ? "Uploading…" : current ? "Replace" : "Upload"}
        <input
          type="file"
          accept={accept}
          className="hidden"
          disabled={uploading}
          onChange={(e) => {
            const file = e.currentTarget.files?.[0];
            if (!file) return;
            const formData = new FormData();
            formData.set("file", file);
            setUploading(true);
            setNote(null);
            startTransition(async () => {
              const state = await uploadBannerMediaAction(banner.id, kind, formData);
              setUploading(false);
              setNote(state.message ?? null);
            });
          }}
        />
      </label>
      {note && <p className="mt-1 text-warn">{note}</p>}
    </div>
  );
}
