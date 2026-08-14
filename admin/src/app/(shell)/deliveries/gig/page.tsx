import type { Metadata } from "next";
import Link from "next/link";
import {
  CarrierShipmentTable,
  type ShipmentColumn,
  type ShipmentTableRow,
} from "@/components/deliveries/CarrierShipmentTable";
import { GigShipmentFilterForm } from "@/components/deliveries/GigShipmentFilterForm";
import { Pagination } from "@/components/Pagination";
import type { SenderLocationRow } from "@/app/(shell)/deliveries/pickup-locations/actions";
import { ApiError } from "@/lib/api";
import {
  gigShipmentsQueryString,
  lastScanStatus,
  parseGigShipmentFilters,
  type GigShipmentPage,
  type GigShipmentRow,
} from "@/lib/deliveries";
import { pageCount } from "@/lib/pagination";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "GIG shipments" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/deliveries/gig";

/** The id-0 entry every origin dropdown needs: pre-Plan-34 shipments and the env
 *  fallback carry an empty snapshot, and both must stay findable in a filtered view. */
const BUILT_IN_ORIGIN = { id: 0, name: "Ogudu (built-in)" };

const STATUS_STYLE: Record<string, string> = {
  quoted: "border-line bg-surface text-muted",
  created: "border-accent/30 bg-accent/10 text-accent",
  in_transit: "border-accent/30 bg-accent/10 text-accent",
  delivered: "border-ok/30 bg-ok/10 text-ok",
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
  { key: "cost", label: "GIG cost", align: "right" },
];

/** One shipment as table cells. The row LINKS to the order — capture and the label
 *  live there, behind their confirm rituals (plan ruling 4). */
function toRow(row: GigShipmentRow): ShipmentTableRow {
  const scan = lastScanStatus(row);
  return {
    id: row.order_number,
    cells: {
      order: (
        <>
          <Link
            href={`/orders/${row.order_number}`}
            className="font-mono font-medium underline-offset-2 hover:underline"
          >
            {row.order_number}
          </Link>
          {row.waybill && <div className="text-xs text-muted">WB {row.waybill}</div>}
        </>
      ),
      // ISO date, not toLocaleDateString: rendered on the server, so a locale format
      // would be the SERVER's locale presented as the reader's.
      placed: (
        <span className="text-xs text-muted">
          {row.placed_at ? row.placed_at.slice(0, 10) : "—"}
        </span>
      ),
      status: (
        <>
          <span
            className={`inline-block rounded border px-1.5 py-0.5 text-xs ${
              STATUS_STYLE[row.status] ?? "border-line bg-surface text-muted"
            }`}
          >
            {row.status.replace(/_/g, " ")}
          </span>
          {scan && <div className="mt-1 max-w-48 text-xs text-muted">{scan}</div>}
        </>
      ),
      origin: row.origin.name || "—",
      destination: (
        <>
          <div>{row.destination || "—"}</div>
          <div className="text-xs text-muted">
            {row.service === "pickup" ? "centre pickup" : "door delivery"}
          </div>
        </>
      ),
      customer: (
        <>
          <div className="truncate">{row.customer_name || "—"}</div>
          <div className="text-xs text-muted">{row.customer_phone}</div>
        </>
      ),
      charged: <span className="font-mono text-xs">{`${row.currency} ${row.charged}`}</span>,
      cost: (
        <span className="font-mono text-xs">
          {row.cost === null ? "—" : `${row.currency} ${row.cost}`}
        </span>
      ),
    },
  };
}

/**
 * `/deliveries/gig` — every GIG shipment, filterable by origin (Plan-35).
 *
 * The operational question this table answers: with two shops, "what must MY shop pack
 * today?" — filter Collecting-from to your origin and every row is a parcel a rider
 * will collect from you.
 *
 * LOADING THIS PAGE WRITES AN AUDIT ROW, like /orders: every row names a customer and
 * their phone, so `AdminGigShipmentListView` is read-audited on purpose.
 */
export default async function GigShipmentsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  await requireAdmin(PATH);

  const raw = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (typeof value === "string") raw.set(key, value);
    else if (Array.isArray(value) && value[0] !== undefined) raw.set(key, value[0]);
  }
  const filters = parseGigShipmentFilters(raw);

  const [shipmentsResult, sendersResult] = await Promise.allSettled([
    (async () => {
      const qs = gigShipmentsQueryString(filters);
      return fetchWithAuthOrBounce<GigShipmentPage>(
        `/admin/gig-shipments/${qs ? `?${qs}` : ""}`,
        PATH,
      );
    })(),
    // Origin choices. Support holds `orders.view` but not `products.manage`, so this
    // 403s for them — the filter control degrades away rather than offering a 403.
    fetchWithAuthOrBounce<SenderLocationRow[]>("/admin/sender-locations/", PATH),
  ]);

  for (const result of [shipmentsResult, sendersResult]) {
    // `redirect()` throws; rethrown so a merely-stale session renews instead of erroring.
    if (result.status === "rejected" && !(result.reason instanceof ApiError)) {
      throw result.reason;
    }
  }

  let error: string | null = null;
  if (shipmentsResult.status === "rejected") {
    const e = shipmentsResult.reason as ApiError;
    error =
      e.status === 403
        ? "Your role does not include access to deliveries."
        : "The shipments could not be loaded.";
  }

  const page = shipmentsResult.status === "fulfilled" ? shipmentsResult.value : null;
  const origins =
    sendersResult.status === "fulfilled" && Array.isArray(sendersResult.value)
      ? [...sendersResult.value.map((s) => ({ id: s.id, name: s.name })), BUILT_IN_ORIGIN]
      : [];

  return (
    <div>
      <div>
        <Link href="/deliveries" className="text-sm text-muted hover:text-foreground">
          ← Deliveries
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">GIG shipments</h1>
        <p className="mt-1 text-sm text-muted">
          Every GIG delivery, newest first. Filter by Collecting-from to see what one
          shop must pack; open an order to capture or print its label.
        </p>
      </div>

      <div className="mt-6">
        <GigShipmentFilterForm filters={filters} origins={origins} />

        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <>
            <p className="mb-2 text-xs text-muted">
              {page?.count ?? 0} {page?.count === 1 ? "shipment" : "shipments"}
            </p>
            <CarrierShipmentTable
              columns={COLUMNS}
              rows={(page?.results ?? []).map(toRow)}
              emptyText="No shipments match those filters. GIG shipments appear here the moment an order chooses a GIG option at checkout."
            />
            <Pagination
              basePath={PATH}
              page={filters.page}
              total={pageCount(page?.count ?? 0)}
              buildQuery={(target) => gigShipmentsQueryString({ ...filters, page: target })}
              label="Shipment pages"
            />
          </>
        )}
      </div>
    </div>
  );
}
