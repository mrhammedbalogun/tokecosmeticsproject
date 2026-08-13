"use client";

/**
 * The product's delete control — rendered only for holders of `products.delete`
 * (the Owner), though the API enforces that again regardless of what renders.
 *
 * TYPE-THE-NAME, NOT A CONFIRM CLICK. Deleting a product takes its variants, prices,
 * stock records and images with it, on a live shop, irreversibly (order history
 * survives: order lines keep their own name snapshot and null their variant link).
 * A "Really delete? OK" dialog is muscle memory within a week; retyping the product's
 * name cannot be done absent-mindedly, and it puts the name of what is about to
 * disappear in front of the person one last time. Same reasoning GitHub applies to
 * repository deletion.
 *
 * `onDelete` is injected like every other write in the editor, so this is testable
 * without a server.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { DeleteState } from "@/app/(shell)/products/[slug]/actions";

export function DeleteProductButton({
  slug,
  name,
  onDelete,
}: {
  slug: string;
  name: string;
  onDelete: (slug: string) => Promise<DeleteState>;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const matches = typed.trim() === name.trim();

  const confirm = () => {
    if (!matches || pending) return;
    setError(null);
    startTransition(async () => {
      let res: DeleteState;
      try {
        res = await onDelete(slug);
      } catch {
        // A dropped request must become a message, not an unhandled rejection —
        // the ProductEditor files document why this catch is load-bearing.
        res = { ok: false, error: "That did not reach the server — check the connection and retry." };
      }
      if (!res.ok) {
        setError(res.error);
        return;
      }
      // `replace`, not `push`: the editor URL now 404s, so leaving it in history
      // gives the back button a broken page — the slug-rename lesson.
      router.replace("/products");
    });
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          setTyped("");
          setError(null);
          setOpen(true);
        }}
        className="shrink-0 rounded border border-warn/40 px-3 py-1.5 text-sm text-warn hover:border-warn hover:bg-warn/5"
      >
        Delete product…
      </button>
    );
  }

  return (
    <div className="w-full max-w-md shrink-0 rounded-[var(--radius-card)] border border-warn/40 bg-warn/5 p-4">
      <p className="text-sm font-medium text-warn">Delete “{name}”?</p>
      <p className="mt-1 text-xs text-muted">
        This removes the product and every variant, price, stock record and image it has —
        permanently. Past orders keep their history. If it should just stop selling, set its
        status to Archived instead.
      </p>
      <label className="mt-3 block text-xs text-muted" htmlFor="delete-product-confirm">
        Type the product’s name to confirm:
      </label>
      <input
        id="delete-product-confirm"
        type="text"
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
        disabled={pending}
        placeholder={name}
        className="mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-warn focus:outline-none"
      />
      {error && <p className="mt-2 text-xs text-warn">{error}</p>}
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={confirm}
          disabled={!matches || pending}
          className="rounded bg-warn px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Deleting…" : "Delete this product"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          disabled={pending}
          className="rounded border border-line px-3 py-1.5 text-sm text-muted hover:border-accent hover:text-foreground"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
