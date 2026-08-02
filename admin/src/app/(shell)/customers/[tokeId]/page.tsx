import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError } from "@/lib/api";
import { formatTotal, sourceLabel, type CustomerDetail } from "@/lib/customers";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Customer" };

/**
 * `/customers/[tokeId]` — one customer, behind `customers.view` (Plan-18b).
 *
 * THE DENSEST PII PAGE IN THE ADMIN: name, email, phone, every saved address, and what
 * they have spent. It is read-audited on the backend, so opening it is recorded.
 *
 * READ-ONLY, and that is a decision rather than a stage this has not reached. Editing an
 * email would silently re-point order history and password resets; deactivating an account
 * is what the deletion flow owns, on a 30-day timer with an anonymisation sweep behind it.
 * A write surface here would be a second way to do both without either's rules — support
 * answers questions from this page, and the customer changes their own details.
 */
export default async function CustomerDetailPage({
  params,
}: {
  params: Promise<{ tokeId: string }>;
}) {
  const { tokeId } = await params;
  const path = `/customers/${tokeId}`;
  await requireAdmin(path);

  let customer: CustomerDetail;
  try {
    customer = await fetchWithAuthOrBounce<CustomerDetail>(
      `/admin/customers/${encodeURIComponent(tokeId)}/`,
      path,
    );
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    // 404 covers "no such customer", "that is a staff account" and "already anonymised" —
    // the backend deliberately does not distinguish, and neither should this page.
    if (e.status === 404) notFound();
    throw e;
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/customers" className="text-sm text-muted hover:text-accent">
          ← Customers
        </Link>
        <h1 className="mt-1 text-lg font-semibold tracking-tight">
          {customer.name || customer.email}
        </h1>
        <p className="mt-1 font-mono text-xs text-muted">{customer.toke_id}</p>
      </div>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Email" value={customer.email} />
        <Field label="Phone" value={customer.phone || "—"} />
        <Field
          label="Email verified"
          value={customer.email_verified_at ? customer.email_verified_at.slice(0, 10) : "Not yet"}
          warn={!customer.email_verified_at}
        />
        <Field label="Came from" value={sourceLabel(customer.legacy_source)} />
        <Field label="Joined" value={customer.date_joined.slice(0, 10)} />
        <Field
          label="Last signed in"
          value={customer.last_login ? customer.last_login.slice(0, 10) : "Never"}
        />
        <Field label="Marketing" value={customer.marketing_consent ? "Opted in" : "No"} />
        <Field
          label="Account"
          value={
            customer.deletion_requested_at
              ? `Deletion requested ${customer.deletion_requested_at.slice(0, 10)}`
              : customer.is_active
                ? "Active"
                : "Deactivated"
          }
          warn={!customer.is_active}
        />
      </section>

      <section>
        <h2 className="text-sm font-semibold">Lifetime value</h2>
        {customer.totals.length === 0 ? (
          <p className="mt-2 text-sm text-muted">No paid orders.</p>
        ) : (
          <div className="mt-2 grid gap-3 sm:grid-cols-3">
            {customer.totals.map((total) => (
              <div key={total.currency} className="rounded-[var(--radius-card)] border border-line p-4">
                <p className="text-xs text-muted">{total.currency}</p>
                <p className="mt-1 text-lg font-semibold tabular-nums">{formatTotal(total)}</p>
                <p className="mt-1 text-xs text-muted">
                  {total.orders} order{total.orders === 1 ? "" : "s"}
                </p>
              </div>
            ))}
          </div>
        )}
        <p className="mt-2 text-xs text-muted">
          Per currency, never added together. Paid orders only — an abandoned bank transfer
          was never money.
        </p>

        {customer.unclaimed_guest_orders > 0 && (
          /* The answer to support's most common question about a migrated customer:
             "why can't they see their old orders?" Deliberately NOT added into the
             lifetime value above — that would attribute money to somebody who has not
             proved the address is theirs. */
          <p className="mt-3 rounded-[var(--radius-card)] border border-warn/40 bg-warn/5 p-3 text-sm">
            {customer.unclaimed_guest_orders} guest order
            {customer.unclaimed_guest_orders === 1 ? "" : "s"} placed with this email
            {" "}belong to no account. They attach automatically once the customer verifies
            their email address — they are not counted above.
          </p>
        )}
      </section>

      <section>
        <h2 className="text-sm font-semibold">Addresses</h2>
        {customer.addresses.length === 0 ? (
          <p className="mt-2 text-sm text-muted">None saved.</p>
        ) : (
          <ul className="mt-2 grid gap-3 sm:grid-cols-2">
            {customer.addresses.map((a) => (
              <li key={a.id} className="rounded-[var(--radius-card)] border border-line p-4 text-sm">
                <p className="text-xs text-muted">
                  {a.label || "Address"}
                  {a.is_default_shipping && " · default shipping"}
                  {a.is_default_billing && " · default billing"}
                </p>
                <p className="mt-1">
                  {[a.line1, a.line2, a.city, a.postcode, a.country_code]
                    .filter(Boolean)
                    .join(", ")}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {customer.legacy_identities.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold">Migrated from</h2>
          <ul className="mt-2 flex flex-wrap gap-2">
            {customer.legacy_identities.map((i) => (
              <li
                key={`${i.store}-${i.wp_user_id}`}
                className="rounded-full border border-line px-3 py-1 text-xs"
              >
                {sourceLabel(i.store)} · WordPress #{i.wp_user_id}
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="text-sm">
        <Link
          href={`/orders?search=${encodeURIComponent(customer.email)}`}
          className="underline underline-offset-2 hover:text-accent"
        >
          This customer&rsquo;s orders →
        </Link>
      </p>
    </div>
  );
}

function Field({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-line p-3">
      <p className="text-xs text-muted">{label}</p>
      <p className={`mt-1 break-words text-sm ${warn ? "text-warn" : ""}`}>{value}</p>
    </div>
  );
}
