"use client";
import type { Region } from "@/components/checkout/RegionSelect";

interface Props {
  suggested: Region;
  selectedName: string;
  onAccept: (region: Region) => void;
  onDismiss: () => void;
}

/** Ruling 7: a prompt, never an override. The customer stays in charge of the
 * field that prices their delivery. */
export function LgaMismatchNudge({ suggested, selectedName, onAccept, onDismiss }: Props) {
  return (
    <div
      role="status"
      className="rounded-[var(--radius-card)] border border-amber-300 bg-amber-50 p-3 text-sm"
    >
      <p>
        Google places this address in <span className="font-medium">{suggested.name}</span>,
        but you selected <span className="font-medium">{selectedName}</span>. The area sets
        your delivery price — which is right?
      </p>
      <div className="mt-2 flex items-center gap-4">
        <button
          type="button"
          onClick={() => onAccept(suggested)}
          className="rounded-[var(--radius-card)] border border-amber-400 bg-amber-100 px-3 py-1 font-medium hover:bg-amber-200"
        >
          Use {suggested.name}
        </button>
        <button
          type="button"
          onClick={onDismiss}
          className="text-muted underline hover:text-foreground"
        >
          Keep {selectedName}
        </button>
      </div>
    </div>
  );
}
