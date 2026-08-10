"use client";

/**
 * One homepage section, edited in its own shape (Home Content rework, 2026-08-06).
 *
 * The old surface was a flat banner table where changing "the second category tile"
 * meant knowing which row that was and picking its placement from a dropdown. Here the
 * section renders the way the shop renders it — a slot grid, a slide strip, or a news
 * list — showing the CURRENT content (artwork included), and you click the tile you
 * want to change. Placement and position are decided by what you clicked.
 *
 * ── WHAT THE TILES SHOW IS WHAT IS LIVE ─────────────────────────────────────────────
 *
 * Slot occupants are computed exactly like the storefront computes them: live banners
 * only, in sort order, mapped onto slots positionally. An empty slot shows the shop's
 * built-in content with a "built-in" badge, because that IS what the customer sees
 * there. Banners that exist but are not showing (scheduled, ended, switched off) would
 * silently distort that picture if they sat in the slots, so they wait in their own
 * list below the grid instead.
 *
 * Reordering swaps neighbours in the LIVE lineup but persists the whole placement's
 * order (sort = index across live and waiting), which also normalises legacy rows that
 * all carried sort 0.
 */
import { startTransition, useState } from "react";
import { reorderBannersAction } from "@/app/(shell)/content/banners/actions";
import { HomeBannerModal } from "@/components/content/HomeBannerModal";
import {
  bannerState,
  placementBanners,
  placementSpec,
  type BannerField,
  type BannerRow,
  type CountryOption,
} from "@/lib/banners";

const STATE_STYLES: Record<string, string> = {
  live: "border-ok/50 text-ok",
  scheduled: "border-accent/50 text-accent",
  ended: "border-line text-muted",
  off: "border-line text-muted",
};

type Defaults = Partial<Record<BannerField, string>>;

interface EditorTarget {
  banner: BannerRow | null;
  /** On create: the built-in content the clicked slot currently shows, so the editor
   * opens pre-filled with what the customer is seeing rather than blank. */
  defaults: Defaults | null;
  presetSort: number;
  heading: string;
}

export function HomePlacementEditor({
  placement,
  banners,
  layout,
  gridClass = "grid-cols-2 md:grid-cols-3",
  itemNoun = "tile",
  countryOptions = [],
}: {
  placement: string;
  /** The full banner list — filtering by placement happens here. */
  banners: BannerRow[];
  /** grid = fixed slots · slides = hero strip · list = text rows (news marquee). */
  layout: "grid" | "slides" | "list";
  /** Tailwind column classes for the grid/slides layouts. */
  gridClass?: string;
  /** What one entry is called in buttons and headings: "tile", "slide", "news item". */
  itemNoun?: string;
  /** Markets for the editor's geo-targeting picker. */
  countryOptions?: CountryOption[];
}) {
  const spec = placementSpec(placement);
  const all = placementBanners(banners, placement);
  const live = all.filter((b) => bannerState(b) === "live");
  const waiting = all.filter((b) => bannerState(b) !== "live");

  const [editor, setEditor] = useState<EditorTarget | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [reordering, setReordering] = useState(false);

  const nextSort = (all.at(-1)?.sort ?? -1) + 1;

  /** Swap two live neighbours, then persist the whole placement's order. */
  const swapLive = (i: number, j: number) => {
    const a = all.indexOf(live[i]);
    const b = all.indexOf(live[j]);
    const order = all.map((x) => x.id);
    [order[a], order[b]] = [order[b], order[a]];
    persistOrder(order);
  };

  /** List layout reorders across the full lineup — the rows ARE the lineup. */
  const swapAll = (i: number, j: number) => {
    const order = all.map((x) => x.id);
    [order[i], order[j]] = [order[j], order[i]];
    persistOrder(order);
  };

  const persistOrder = (order: number[]) => {
    setReordering(true);
    setMessage(null);
    startTransition(async () => {
      const state = await reorderBannersAction(order);
      setReordering(false);
      setMessage(state.message ?? null);
    });
  };

  const openEdit = (banner: BannerRow, position: string) =>
    setEditor({ banner, defaults: null, presetSort: banner.sort, heading: `${spec.label} · ${position}` });
  const openCreate = (position: string, defaults: Defaults | null = null) =>
    setEditor({ banner: null, defaults, presetSort: nextSort, heading: `${spec.label} · ${position}` });

  return (
    <div className="space-y-3">
      {message && (
        <p className="rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
          {message}
        </p>
      )}

      {layout === "list" ? (
        <NewsList
          spec={spec}
          all={all}
          reordering={reordering}
          onSwap={swapAll}
          onEdit={(b, i) => openEdit(b, `item ${i + 1}`)}
          onAdd={() => openCreate("new item")}
          itemNoun={itemNoun}
        />
      ) : (
        <>
          <div className={`grid gap-3 ${gridClass}`}>
            {(layout === "grid" ? Array.from({ length: spec.slots ?? 1 }) : [...live, null]).map(
              (_, i) => {
                // grid: one card per slot. slides: one card per live slide plus the
                // trailing "add" card (the null sentinel).
                if (layout === "slides" && i === live.length) {
                  return (
                    <AddCard
                      key="add"
                      aspect={spec.aspect}
                      label={`Add ${itemNoun}`}
                      onClick={() =>
                        // The first slide replaces the shop's built-in one, so it opens
                        // pre-filled with that content; later slides are additions and
                        // start blank.
                        openCreate(
                          `${itemNoun} ${live.length + 1}`,
                          live.length === 0 ? (spec.defaults[0] ?? null) : null,
                        )
                      }
                    />
                  );
                }
                const occupant = live[i] ?? null;
                const fallback: Defaults | null =
                  layout === "grid"
                    ? // Positional merge: each empty slot keeps its own built-in.
                      (spec.defaults[i] ?? null)
                    : // Unlimited sections: built-ins only exist while NOTHING is live.
                      live.length === 0
                      ? (spec.defaults[i] ?? null)
                      : null;
                const position = `${itemNoun} ${i + 1}`;
                return (
                  <TileCard
                    key={occupant?.id ?? `slot-${i}`}
                    banner={occupant}
                    fallback={fallback}
                    aspect={spec.aspect}
                    position={position}
                    showPosition={(spec.slots ?? 2) > 1 || layout === "slides"}
                    disabled={reordering}
                    onEdit={() =>
                      occupant ? openEdit(occupant, position) : openCreate(position, fallback)
                    }
                    onLeft={occupant && i > 0 ? () => swapLive(i, i - 1) : undefined}
                    onRight={
                      occupant && i < live.length - 1 ? () => swapLive(i, i + 1) : undefined
                    }
                  />
                );
              },
            )}
          </div>
          {layout === "slides" && live.length === 0 && (
            <p className="text-xs text-muted">
              The shop is showing its built-in {itemNoun} (previewed above). Your first live{" "}
              {itemNoun} replaces it.
            </p>
          )}
          {waiting.length > 0 && (
            <WaitingList
              waiting={waiting}
              itemNoun={itemNoun}
              onEdit={(b) => openEdit(b, "not showing")}
            />
          )}
        </>
      )}

      {editor && (
        <HomeBannerModal
          spec={spec}
          banner={editor.banner}
          defaults={editor.defaults}
          presetSort={editor.presetSort}
          heading={editor.heading}
          countryOptions={countryOptions}
          onClose={() => setEditor(null)}
        />
      )}
    </div>
  );
}

/* ────────────────────────────── pieces ────────────────────────────── */

/** A tile as the shop shows it: artwork (or the built-in look), text, one Edit door. */
function TileCard({
  banner,
  fallback,
  aspect,
  position,
  showPosition,
  disabled,
  onEdit,
  onLeft,
  onRight,
}: {
  banner: BannerRow | null;
  fallback: Defaults | null;
  aspect: string;
  position: string;
  showPosition: boolean;
  disabled: boolean;
  onEdit: () => void;
  onLeft?: () => void;
  onRight?: () => void;
}) {
  const content = banner ?? fallback;
  return (
    <figure className="min-w-0">
      <div
        className={`relative overflow-hidden rounded-[var(--radius-card)] border ${aspect} ${
          banner ? "border-line" : "border-dashed border-line"
        }`}
      >
        {banner ? (
          <TileThumb banner={banner} />
        ) : (
          <div className="absolute inset-0 bg-gradient-to-br from-surface to-line/60" />
        )}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-2.5 pt-8">
          {content?.subtitle && (
            <p className="truncate text-[10px] uppercase tracking-[0.14em] text-white/75">
              {content.subtitle}
            </p>
          )}
          <p className="truncate text-sm font-medium text-white">
            {content?.title || <span className="text-white/60">empty</span>}
          </p>
          {content?.tagline && (
            <p className="truncate text-[11px] text-white/75">{content.tagline}</p>
          )}
          {(content?.cta_text || content?.cta_url) && (
            <p className="truncate text-[10px] text-white/60">
              {content.cta_text ? `${content.cta_text} → ` : "→ "}
              {content.cta_url || "no link yet"}
            </p>
          )}
        </div>
        {!banner && (
          <span className="absolute right-2 top-2 rounded-full border border-line bg-background/85 px-2 py-0.5 text-[10px] text-muted">
            built-in
          </span>
        )}
      </div>
      <figcaption className="mt-1.5 flex items-center gap-1.5 text-xs">
        {showPosition && <span className="text-muted">{position}</span>}
        <span className="flex-1" />
        {onLeft && (
          <button
            type="button"
            onClick={onLeft}
            disabled={disabled}
            aria-label={`Move ${position} earlier`}
            className="rounded border border-line px-2 py-1 hover:border-accent disabled:opacity-40"
          >
            ←
          </button>
        )}
        {onRight && (
          <button
            type="button"
            onClick={onRight}
            disabled={disabled}
            aria-label={`Move ${position} later`}
            className="rounded border border-line px-2 py-1 hover:border-accent disabled:opacity-40"
          >
            →
          </button>
        )}
        <button
          type="button"
          onClick={onEdit}
          className="rounded border border-line px-2.5 py-1 font-medium hover:border-accent"
        >
          {banner ? "Edit" : "Replace"}
        </button>
      </figcaption>
    </figure>
  );
}

function TileThumb({ banner }: { banner: BannerRow }) {
  if (banner.video) {
    return (
      <video
        src={banner.video}
        poster={banner.image ?? undefined}
        preload="metadata"
        muted
        playsInline
        className="absolute inset-0 h-full w-full object-cover"
      />
    );
  }
  if (banner.image) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- admin thumbnail of an uploaded file; next/image buys nothing here.
      <img src={banner.image} alt="" className="absolute inset-0 h-full w-full object-cover" />
    );
  }
  return <div className="absolute inset-0 bg-gradient-to-br from-[#7a5c42] to-[#2e2119]" />;
}

function AddCard({
  aspect,
  label,
  onClick,
}: {
  aspect: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`grid place-items-center rounded-[var(--radius-card)] border border-dashed border-line text-sm text-muted transition hover:border-accent hover:text-accent ${aspect}`}
    >
      + {label}
    </button>
  );
}

/** The news marquee is text, so it edits as rows — every item, live or not, in order. */
function NewsList({
  spec,
  all,
  reordering,
  onSwap,
  onEdit,
  onAdd,
  itemNoun,
}: {
  spec: ReturnType<typeof placementSpec>;
  all: BannerRow[];
  reordering: boolean;
  onSwap: (i: number, j: number) => void;
  onEdit: (banner: BannerRow, index: number) => void;
  onAdd: () => void;
  itemNoun: string;
}) {
  const anyLive = all.some((b) => bannerState(b) === "live");
  return (
    <div className="space-y-3">
      <ul className="divide-y divide-line rounded-[var(--radius-card)] border border-line text-sm">
        {all.map((item, i) => {
          const state = bannerState(item);
          return (
            <li key={item.id} className="flex items-center gap-3 p-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate">{item.title}</p>
                {item.cta_url && <p className="truncate text-xs text-muted">→ {item.cta_url}</p>}
              </div>
              <StateBadge banner={item} state={state} />
              <button
                type="button"
                onClick={() => onSwap(i, i - 1)}
                disabled={reordering || i === 0}
                aria-label="Move up"
                className="rounded border border-line px-2 py-1 text-xs hover:border-accent disabled:opacity-40"
              >
                ↑
              </button>
              <button
                type="button"
                onClick={() => onSwap(i, i + 1)}
                disabled={reordering || i === all.length - 1}
                aria-label="Move down"
                className="rounded border border-line px-2 py-1 text-xs hover:border-accent disabled:opacity-40"
              >
                ↓
              </button>
              <button
                type="button"
                onClick={() => onEdit(item, i)}
                className="rounded border border-line px-2.5 py-1 text-xs font-medium hover:border-accent"
              >
                Edit
              </button>
            </li>
          );
        })}
        {!anyLive &&
          spec.defaults.map((d, i) => (
            <li key={`default-${i}`} className="flex items-center gap-3 p-2.5 text-muted">
              <p className="min-w-0 flex-1 truncate">{d.title}</p>
              <span className="rounded-full border border-line px-2 py-0.5 text-[10px]">
                built-in
              </span>
            </li>
          ))}
      </ul>
      {!anyLive && (
        <p className="text-xs text-muted">
          The shop is showing its built-in messages. Your first live {itemNoun} replaces the
          whole set.
        </p>
      )}
      <button
        type="button"
        onClick={onAdd}
        className="rounded border border-dashed border-line px-3 py-1.5 text-sm text-muted transition hover:border-accent hover:text-accent"
      >
        + Add {itemNoun}
      </button>
    </div>
  );
}

/** Banners that exist but are not showing — scheduled, ended, or switched off. */
function WaitingList({
  waiting,
  itemNoun,
  onEdit,
}: {
  waiting: BannerRow[];
  itemNoun: string;
  onEdit: (banner: BannerRow) => void;
}) {
  return (
    <div>
      <p className="text-xs font-medium text-muted">Not showing right now</p>
      <ul className="mt-1.5 divide-y divide-line rounded-[var(--radius-card)] border border-line text-sm">
        {waiting.map((item) => (
          <li key={item.id} className="flex items-center gap-3 p-2">
            <div className="relative h-10 w-14 shrink-0 overflow-hidden rounded border border-line">
              <TileThumb banner={item} />
            </div>
            <p className="min-w-0 flex-1 truncate">{item.title || `untitled ${itemNoun}`}</p>
            <StateBadge banner={item} state={bannerState(item)} />
            <button
              type="button"
              onClick={() => onEdit(item)}
              className="rounded border border-line px-2.5 py-1 text-xs font-medium hover:border-accent"
            >
              Edit
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StateBadge({ banner, state }: { banner: BannerRow; state: string }) {
  const when =
    state === "scheduled" && banner.starts_at
      ? ` ${banner.starts_at.slice(0, 10)}`
      : state === "ended" && banner.ends_at
        ? ` ${banner.ends_at.slice(0, 10)}`
        : "";
  return (
    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] ${STATE_STYLES[state]}`}>
      {state}
      {when}
    </span>
  );
}
