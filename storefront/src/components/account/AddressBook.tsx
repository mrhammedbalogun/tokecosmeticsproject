"use client";

/**
 * The account address book (Plan-15d Task 2): list/add/edit/delete + set-default
 * shipping/billing. No optimistic state — every successful mutation re-GETs
 * /api/addresses and replaces the list wholesale (plan ruling: the book is small,
 * correctness beats latency). A mutation failure leaves the list untouched and shows
 * an inline message instead.
 */
import { useState } from "react";
import type { Address } from "@/components/checkout/address-fields";
import { AddressForm } from "@/components/account/AddressForm";

type Mode = { kind: "list" } | { kind: "add" } | { kind: "edit"; address: Address };

const GENERIC_ERROR = "Something went wrong — please try again.";

/** Free-text locality line for the card (distinct from address-fields.ts's
 * summarizeAddress, which is a "line1, city" summary built for checkout's radio
 * cards). NG addresses carry region *ids* only client-side — no name lookup here — so
 * this renders nothing for them, same limitation address-fields.ts documents. */
function localityLine(addr: Address): string | null {
  const parts = [addr.city_text, addr.state_text, addr.postcode].filter(
    (p): p is string => Boolean(p && p.trim())
  );
  return parts.length ? parts.join(", ") : null;
}

function omit(rec: Record<number, string>, id: number): Record<number, string> {
  const next = { ...rec };
  delete next[id];
  return next;
}

export function AddressBook({ initial }: { initial: Address[] }) {
  const [addresses, setAddresses] = useState<Address[]>(initial);
  const [mode, setMode] = useState<Mode>({ kind: "list" });
  const [cardErrors, setCardErrors] = useState<Record<number, string>>({});

  async function refresh() {
    const res = await fetch("/api/addresses");
    if (res.ok) {
      const data: Address[] = await res.json().catch(() => []);
      setAddresses(data);
    }
  }

  function handleSaved(_saved: Address) {
    setMode({ kind: "list" });
    void refresh();
  }

  async function handleDelete(id: number) {
    setCardErrors((prev) => omit(prev, id));
    try {
      const res = await fetch(`/api/addresses/${id}`, { method: "DELETE" });
      if (!res.ok) {
        setCardErrors((prev) => ({ ...prev, [id]: GENERIC_ERROR }));
        return;
      }
      await refresh();
    } catch {
      setCardErrors((prev) => ({ ...prev, [id]: GENERIC_ERROR }));
    }
  }

  async function handleSetDefault(id: number, kind: "shipping" | "billing") {
    setCardErrors((prev) => omit(prev, id));
    try {
      const res = await fetch(`/api/addresses/${id}/default`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind }),
      });
      if (!res.ok) {
        setCardErrors((prev) => ({ ...prev, [id]: GENERIC_ERROR }));
        return;
      }
      await refresh();
    } catch {
      setCardErrors((prev) => ({ ...prev, [id]: GENERIC_ERROR }));
    }
  }

  if (mode.kind !== "list") {
    return (
      <AddressForm
        initial={mode.kind === "edit" ? mode.address : undefined}
        onSaved={handleSaved}
        onCancel={() => setMode({ kind: "list" })}
      />
    );
  }

  if (addresses.length === 0) {
    return (
      <div>
        <p className="text-sm text-muted">No addresses yet</p>
        <button
          type="button"
          onClick={() => setMode({ kind: "add" })}
          className="mt-3 rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong"
        >
          Add your first address
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <button
        type="button"
        onClick={() => setMode({ kind: "add" })}
        className="text-sm font-medium text-accent underline hover:text-accent-strong"
      >
        Add address
      </button>
      <ul className="space-y-3">
        {addresses.map((address) => (
          <AddressCard
            key={address.id}
            addr={address}
            error={cardErrors[address.id]}
            onEdit={() => setMode({ kind: "edit", address })}
            onDelete={() => handleDelete(address.id)}
            onSetDefault={(kind) => handleSetDefault(address.id, kind)}
          />
        ))}
      </ul>
    </div>
  );
}

function AddressCard({
  addr,
  error,
  onEdit,
  onDelete,
  onSetDefault,
}: {
  addr: Address;
  error?: string;
  onEdit: () => void;
  onDelete: () => void;
  onSetDefault: (kind: "shipping" | "billing") => void;
}) {
  // Two-step delete: the first click only flips this card to a confirm state, the
  // second click actually deletes. Local to the card (not the list) so confirming one
  // address never bleeds into another.
  const [confirming, setConfirming] = useState(false);

  function handleDeleteClick() {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    onDelete();
  }

  const locality = localityLine(addr);
  const fullName = [addr.first_name, addr.last_name].filter(Boolean).join(" ");

  return (
    <li className="rounded-[var(--radius-card)] border border-line p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          {addr.label && <p className="font-medium">{addr.label}</p>}
          <p className={addr.label ? "text-sm text-muted" : "font-medium"}>{fullName}</p>
        </div>
        {(addr.is_default_shipping || addr.is_default_billing) && (
          <div className="flex flex-wrap gap-2">
            {addr.is_default_shipping && (
              <span className="rounded-full bg-beige px-2 py-0.5 text-xs text-muted">
                Default shipping
              </span>
            )}
            {addr.is_default_billing && (
              <span className="rounded-full bg-beige px-2 py-0.5 text-xs text-muted">
                Default billing
              </span>
            )}
          </div>
        )}
      </div>

      <p className="mt-2 text-sm text-muted">
        {addr.line1}
        {addr.line2 ? `, ${addr.line2}` : ""}
      </p>
      {locality && <p className="text-sm text-muted">{locality}</p>}
      {addr.phone && <p className="text-sm text-muted">{addr.phone}</p>}

      {error && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-4 text-sm">
        <button
          type="button"
          onClick={onEdit}
          className="text-accent-strong underline hover:text-accent"
        >
          Edit
        </button>
        {!addr.is_default_shipping && (
          <button
            type="button"
            onClick={() => onSetDefault("shipping")}
            className="text-accent-strong underline hover:text-accent"
          >
            Set default shipping
          </button>
        )}
        {!addr.is_default_billing && (
          <button
            type="button"
            onClick={() => onSetDefault("billing")}
            className="text-accent-strong underline hover:text-accent"
          >
            Set default billing
          </button>
        )}
        <button
          type="button"
          onClick={handleDeleteClick}
          className="text-red-700 underline hover:text-red-800"
        >
          {confirming ? "Confirm delete?" : "Delete"}
        </button>
      </div>
    </li>
  );
}
