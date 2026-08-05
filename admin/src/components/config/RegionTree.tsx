"use client";

/**
 * The state/area accordion with tri-state checkboxes — extracted from CoveragePicker so
 * the create wizard and the coverage page render the SAME tree with the same rules:
 * ticking a state selects the STATE ROW (areas added later are covered automatically),
 * and a partial pick shows as indeterminate rather than looking like no pick.
 */
import { useState } from "react";
import { stateSelection, type StateNode } from "@/lib/regions";

export function RegionTree({
  tree,
  selected,
  onToggle,
  areaLabel = "areas",
}: {
  tree: StateNode[];
  selected: Set<number>;
  onToggle: (id: number) => void;
  /** Plural, lowercase — "LGAs", "counties" — used in the "N …" expander. */
  areaLabel?: string;
}) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  return (
    <ul className="max-h-[28rem] divide-y divide-line overflow-y-auto rounded border border-line">
      {tree.map((node) => {
        const selection = stateSelection(node, selected);
        const isOpen = expanded.has(node.state.id);
        return (
          <li key={node.state.id}>
            <div className="flex items-center gap-2 px-3 py-2">
              <input
                type="checkbox"
                checked={selection === "all"}
                ref={(el) => {
                  // The tri-state. Without it a partial pick looks like no pick.
                  if (el) el.indeterminate = selection === "some";
                }}
                onChange={() => onToggle(node.state.id)}
                className="h-4 w-4 rounded border-line"
                aria-label={`Serve all of ${node.state.name}`}
              />
              <button
                type="button"
                onClick={() =>
                  setExpanded((current) => {
                    const next = new Set(current);
                    if (next.has(node.state.id)) next.delete(node.state.id);
                    else next.add(node.state.id);
                    return next;
                  })
                }
                className="flex flex-1 items-center justify-between text-left text-sm hover:text-accent"
                disabled={node.areas.length === 0}
              >
                <span>
                  {node.state.name}
                  {selection === "some" && (
                    <span className="ml-2 text-xs text-accent">part</span>
                  )}
                  {!node.state.is_active && (
                    <span className="ml-2 text-xs text-muted">(hidden)</span>
                  )}
                </span>
                {node.areas.length > 0 && (
                  <span className="text-xs text-muted">
                    {node.areas.length} {areaLabel} {isOpen ? "▲" : "▼"}
                  </span>
                )}
              </button>
            </div>
            {isOpen && node.areas.length > 0 && (
              <ul className="bg-surface/50 pb-2 pl-9 pr-3">
                {node.areas.map((area) => (
                  <li key={area.id}>
                    <label className="flex items-center gap-2 py-0.5 text-sm">
                      <input
                        type="checkbox"
                        checked={selected.has(area.id) || selected.has(node.state.id)}
                        disabled={selected.has(node.state.id)}
                        onChange={() => onToggle(area.id)}
                        className="h-4 w-4 rounded border-line"
                      />
                      <span className={selected.has(node.state.id) ? "text-muted" : ""}>
                        {area.name}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ul>
  );
}
