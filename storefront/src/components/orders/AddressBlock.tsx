/** The address snapshot on an order is an untyped JSON blob (see OrderDetail.shipping_
 * address in lib/orders.ts) — it's a point-in-time copy of an Address row, not a
 * live reference, so it's read defensively here rather than assumed to match the
 * Address shape exactly. */
function str(addr: Record<string, unknown> | null, key: string): string | undefined {
  const v = addr?.[key];
  return typeof v === "string" && v.trim() ? v : undefined;
}

export function AddressSummary({ address }: { address: Record<string, unknown> | null }) {
  if (!address) return <p className="text-sm text-muted">No address on file.</p>;
  const name = [str(address, "first_name"), str(address, "last_name")].filter(Boolean).join(" ");
  const lines = [
    name,
    str(address, "line1"),
    str(address, "line2"),
    [str(address, "city_text"), str(address, "state_text")].filter(Boolean).join(", "),
    str(address, "postcode"),
    str(address, "phone"),
  ].filter((l): l is string => Boolean(l && l.trim()));

  if (lines.length === 0) return <p className="text-sm text-muted">No address on file.</p>;

  return (
    <address className="text-sm not-italic text-muted">
      {lines.map((line, i) => (
        <span key={i} className="block">
          {line}
        </span>
      ))}
    </address>
  );
}
