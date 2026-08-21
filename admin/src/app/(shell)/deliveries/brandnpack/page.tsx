import type { Metadata } from "next";
import Link from "next/link";
import {
  CarrierShipmentTable,
  type ShipmentColumn,
  type ShipmentTableRow,
} from "@/components/deliveries/CarrierShipmentTable";
import { PartnerShipmentFilterForm } from "@/components/deliveries/PartnerShipmentFilterForm";
import { Pagination } from "@/components/Pagination";
import { ApiError } from "@/lib/api";
import {
  parsePartnerShipmentFilters,
  partnerShipmentsQueryString,
  type PartnerShipmentPage,
  type PartnerShipmentRow,
} from "@/lib/deliveries";
import { statusLabel } from "@/lib/orders";
import { pageCount } from "@/lib/pagination";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "BrandnPack shipments" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/deliveries/brandnpack";

/** This page is ONE partner's table — the pin goes to the backend call only, never
 *  into the page's own URL. A second partner gets its own card and pin. */
const PARTNER_CODE = "brandnpack";

/** The ORDER status vocabulary (a partner shipment has none of its own), styled as
 *  the orders table styles it — pending_payment loud on purpose: this table is a
 *  dispatch worklist, and an unpaid row must not read as a parcel to hand over. */
const STATUS_STYLE: Record<string, string> = {
  pending_payment: "border-warn/30 bg-warn/5 text-warn",
  processing: "border-accent/30 bg-accent/10 text-accent",
  shipped: "border-accent/30 bg-accent/10 text-accent",
  delivered: "border-ok/30 bg-ok/10 text-ok",
  completed: "border-ok/30 bg-ok/10 text-ok",
  on_hold: "border-warn/30 bg-warn/5 text-warn",
  expired: "border-line bg-surface text-muted",
  cancelled: "border-line bg-surface text-muted",
  refunded: "border-line bg-surface text-muted",
};

const COLUMNS: ShipmentColumn[] = [
  { key: "order", label: "Order" },
  { key: "placed", label: "Placed" },
  { key: "status", label: "Status" },
  { key: "zone", label: "Zone" },
  { key: "destination", label: "Destination" },
  { key: "customer", label: "Customer" },
  { key: "charged", label: "Charged", align: "right" },
  { key: "cost", label: "Partner cost", align: "right" },
];

/** One shipment as table cells. The row LINKS to the order — status moves live
 *  there, behind the transition endpoint's rules; this table only reads. */
function toRow(row: PartnerShipmentRow): ShipmentTableRow {
  return {
    id: row.order_number,
    cells: {
      order: (
        <Link
          href={`/orders/${row.order_number}`}
          className="font-mono font-medium underline-offset-2 hover:underline"
        >
          {row.order_number}
        </Link>
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
            {statusLabel(row.status)}
          </span>
          {/* The machine stamp, shown even when a refund re-statused the order:
              "the partner did deliver this" is what their invoice bills against. */}
          {row.delivered_at && (
            <div className="mt-1 text-xs text-muted">
              delivered {row.delivered_at.slice(0, 10)}
            </div>
          )}
        </>
      ),
      zone: (
        <>
          <div>{row.lcda || "—"}</div>
          {row.dispatch_zone && (
            <div className="text-xs text-muted">{row.dispatch_zone}</div>
          )}
        </>
      ),
      destination: row.destination || "—",
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
 * `/deliveries/brandnpack` — every order handed to BrandnPack, newest first: the
 * GIG table's sibling for a courier with no API. Charged vs Partner cost is the
 * fee-mask margin; the delivered stamp under Status is what the partner's invoice
 * reconciles against (filter "Partner delivered" to count a month).
 *
 * LOADING THIS PAGE WRITES AN AUDIT ROW, like /deliveries/gig: every row names a
 * customer and their phone, so `AdminPartnerShipmentListView` is read-audited on
 * purpose.
 */
export default async function BrandnPackShipmentsPage({
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
  const filters = parsePartnerShipmentFilters(raw);

  let page: PartnerShipmentPage | null = null;
  let error: string | null = null;
  try {
    const qs = new URLSearchParams(partnerShipmentsQueryString(filters));
    qs.set("partner", PARTNER_CODE);
    page = await fetchWithAuthOrBounce<PartnerShipmentPage>(
      `/admin/partner-shipments/?${qs}`,
      PATH,
    );
  } catch (e) {
    // `redirect()` throws; rethrown so a merely-stale session renews instead of erroring.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include access to deliveries."
        : "The shipments could not be loaded.";
  }

  return (
    <div>
      <div>
        <Link href="/deliveries" className="text-sm text-muted hover:text-foreground">
          ← Deliveries
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">BrandnPack shipments</h1>
        <p className="mt-1 text-sm text-muted">
          Every order handed to BrandnPack, newest first. Status is the order&apos;s —
          open an order to move it; filter Partner delivered to count what BrandnPack
          should invoice.
        </p>
      </div>

      <div className="mt-6">
        <PartnerShipmentFilterForm filters={filters} basePath={PATH} />

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
              emptyText="No shipments match those filters. BrandnPack shipments appear here the moment an order chooses a BrandnPack option at checkout."
            />
            <Pagination
              basePath={PATH}
              page={filters.page}
              total={pageCount(page?.count ?? 0)}
              buildQuery={(target) =>
                partnerShipmentsQueryString({ ...filters, page: target })
              }
              label="Shipment pages"
            />
          </>
        )}
      </div>
    </div>
  );
}
