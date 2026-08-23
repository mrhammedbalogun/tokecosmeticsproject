import type { Metadata } from "next";
import Link from "next/link";
import {
  CarrierShipmentTable,
  type ShipmentColumn,
  type ShipmentTableRow,
} from "@/components/deliveries/CarrierShipmentTable";
import { AajShipmentFilterForm } from "@/components/deliveries/AajShipmentFilterForm";
import { Pagination } from "@/components/Pagination";
import type { SenderLocationRow } from "@/app/(shell)/deliveries/pickup-locations/actions";
import { ApiError } from "@/lib/api";
import {
  aajLastScan,
  aajShipmentsQueryString,
  parseAajShipmentFilters,
  type AajShipmentPage,
  type AajShipmentRow,
} from "@/lib/deliveries";
import { pageCount } from "@/lib/pagination";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "AAJ shipments" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/deliveries/aaj";

const STATUS_STYLE: Record<string, string> = {
  quoted: "border-line bg-surface text-muted",
  booked: "border-line bg-surface text-muted",
  created: "border-accent/30 bg-accent/10 text-accent",
  in_transit: "border-accent/30 bg-accent/10 text-accent",
  delivered: "border-ok/30 bg-ok/10 text-ok",
  returned: "border-warn/30 bg-warn/5 text-warn",
  voided: "border-line bg-surface text-muted",
  create_unconfirmed: "border-warn/30 bg-warn/5 text-warn",
  abandoned: "border-line bg-surface text-muted",
};

const COLUMNS: ShipmentColumn[] = [
  { key: "order", label: "Order" },
  { key: "placed", label: "Placed" },
  { key: "status", label: "Status" },
  { key: "origin", label: "Collecting from" },
  { key: "destination", label: "Destination" },
  { key: "customer", label: "Customer" },
  { key: "charged", label: "Charged", align: "right" },
  { key: "cost", label: "AAJ cost", align: "right" },
];

/** One shipment as table cells. The row LINKS to the order — capture, check, void and
 *  the label live there, behind their confirm rituals. */
function toRow(row: AajShipmentRow): ShipmentTableRow {
  const scan = aajLastScan(row);
  return {
    id: row.order_number,
    cells: {
      order: (
        <>
          <Link href={`/orders/${row.order_number}`} className="font-mono font-medium underline-offset-2 hover:underline">
            {row.order_number}
          </Link>
          {row.tracking_id && <div className="text-xs text-muted">AAJ {row.tracking_id}</div>}
        </>
      ),
      placed: <span className="text-xs text-muted">{row.placed_at ? row.placed_at.slice(0, 10) : "—"}</span>,
      status: (
        <>
          <span className={`inline-block rounded border px-1.5 py-0.5 text-xs ${STATUS_STYLE[row.status] ?? "border-line bg-surface text-muted"}`}>
            {row.status.replace(/_/g, " ")}
          </span>
          {scan && <div className="mt-1 max-w-48 text-xs text-muted">{scan}</div>}
        </>
      ),
      origin: (
        <>
          <div>{row.origin.name || "—"}</div>
          {row.origin.state && <div className="text-xs text-muted">{row.origin.state}</div>}
        </>
      ),
      destination: (
        <>
          <div>{row.destination || "—"}</div>
          <div className="text-xs text-muted">door delivery</div>
        </>
      ),
      customer: (
        <>
          <div className="truncate">{row.customer_name || "—"}</div>
          <div className="text-xs text-muted">{row.customer_phone}</div>
        </>
      ),
      charged: (
        <>
          <span className="font-mono text-xs">{`${row.currency} ${row.charged}`}</span>
          {/* The retail quote the customer was priced from, when a free_over or a mask
              made the charge differ from it. */}
          {row.quote_total && row.quote_total !== row.charged && (
            <div className="text-[11px] text-muted">quote {row.quote_total}</div>
          )}
        </>
      ),
      cost: <span className="font-mono text-xs">{row.cost === null ? "—" : `${row.currency} ${row.cost}`}</span>,
    },
  };
}

/**
 * `/deliveries/aaj` — every AAJ Express shipment (Plan-43), the GIG table's sibling.
 * LOADING THIS PAGE WRITES AN AUDIT ROW: every row names a customer and their phone.
 */
export default async function AajShipmentsPage({ searchParams }: { searchParams: SearchParams }) {
  await requireAdmin(PATH);

  const raw = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (typeof value === "string") raw.set(key, value);
    else if (Array.isArray(value) && value[0] !== undefined) raw.set(key, value[0]);
  }
  const filters = parseAajShipmentFilters(raw);

  const [shipmentsResult, sendersResult] = await Promise.allSettled([
    (async () => {
      const qs = aajShipmentsQueryString(filters);
      return fetchWithAuthOrBounce<AajShipmentPage>(`/admin/aaj-shipments/${qs ? `?${qs}` : ""}`, PATH);
    })(),
    fetchWithAuthOrBounce<SenderLocationRow[]>("/admin/sender-locations/", PATH),
  ]);

  for (const result of [shipmentsResult, sendersResult]) {
    if (result.status === "rejected" && !(result.reason instanceof ApiError)) throw result.reason;
  }

  let error: string | null = null;
  if (shipmentsResult.status === "rejected") {
    const e = shipmentsResult.reason as ApiError;
    error = e.status === 403 ? "Your role does not include access to deliveries." : "The shipments could not be loaded.";
  }

  const page = shipmentsResult.status === "fulfilled" ? shipmentsResult.value : null;
  const origins =
    sendersResult.status === "fulfilled" && Array.isArray(sendersResult.value)
      ? sendersResult.value.map((s) => ({ id: s.id, name: s.name }))
      : [];

  return (
    <div>
      <div>
        <Link href="/deliveries" className="text-sm text-muted hover:text-foreground">
          ← Deliveries
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">AAJ Express shipments</h1>
        <p className="mt-1 text-sm text-muted">
          Every AAJ delivery, newest first. Charged is what the customer paid (from AAJ&rsquo;s
          retail quote); AAJ cost is what our account was charged at booking — the difference
          is margin. Open an order to book, charge, void or print its label.
        </p>
      </div>

      <div className="mt-6">
        <AajShipmentFilterForm filters={filters} origins={origins} />

        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">{error}</p>
        ) : (
          <>
            <p className="mb-2 text-xs text-muted">
              {page?.count ?? 0} {page?.count === 1 ? "shipment" : "shipments"}
            </p>
            <CarrierShipmentTable
              columns={COLUMNS}
              rows={(page?.results ?? []).map(toRow)}
              emptyText="No shipments match those filters. AAJ shipments appear here the moment an order chooses the AAJ option at checkout."
            />
            <Pagination
              basePath={PATH}
              page={filters.page}
              total={pageCount(page?.count ?? 0)}
              buildQuery={(target) => aajShipmentsQueryString({ ...filters, page: target })}
              label="Shipment pages"
            />
          </>
        )}
      </div>
    </div>
  );
}
