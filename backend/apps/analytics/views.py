"""Admin reports (Plan-20a).

`reports.view` — the third scope this project declared before anything used it, after
`cms.manage` (fixed in 19a) and `settings.manage` (19b). Until now Owner and Manager held
it and it reached nothing, while the nav showed a Reports link that 404'd.

── TWO GATES, NOT ONE ──────────────────────────────────────────────────────────────

Reading an aggregate and taking a file of customer emails are different acts, and this
codebase already ruled on the difference: `AdminOrderCSVExportView` sits behind
`orders.manage` — a scope ABOVE the list's `orders.view` — and sets `audit_reads = True`,
because "a dump of every customer is not Support's to take".

So the reports themselves are `reports.view`, and **any export that names customers
requires `orders.manage`**. That is also why the spec's XLSX-to-S3 pipeline was declined:
a signed bucket link is an export with no scope check and no audit row at all.
"""
from datetime import date, datetime, timedelta

from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope, scopes_for_user
from apps.analytics import queries
from apps.analytics.csv_out import stream_csv
from apps.core.audit import AdminAuditMixin

# Every report this stage serves, and the function behind it. A dict rather than a
# per-report view class: they differ only in which aggregate they call.
REPORTS = {
    "revenue": queries.revenue_totals,
    "revenue_by_day": queries.revenue_by_day,
    "orders_by_status": queries.orders_by_status,
    "top_products": queries.top_products,
    "sales_by_category": queries.sales_by_category,
    "top_customers": queries.top_customers,
    "coupons": queries.coupon_performance,
}

# Reports whose rows name a customer. Exporting one is bulk egress of personal data and
# needs the higher scope; reading it on screen does not.
CUSTOMER_NAMING = {"top_customers"}


def _parse_window(request) -> tuple[queries.Range | None, str | None]:
    """`?start=&end=&country=`, defaulting to the last 30 days.

    `end` is INCLUSIVE for the caller and exclusive internally — a person asking for
    1–31 August means the 31st included, and getting a silently short month is the kind of
    off-by-one that makes somebody distrust every number on the page.
    """
    today = timezone.localdate()
    raw_start = request.query_params.get("start")
    raw_end = request.query_params.get("end")
    try:
        start = date.fromisoformat(raw_start) if raw_start else today - timedelta(days=29)
        end_inclusive = date.fromisoformat(raw_end) if raw_end else today
    except ValueError:
        return None, "Dates must be YYYY-MM-DD."
    if end_inclusive < start:
        return None, "The end date cannot be before the start date."

    tz = timezone.get_current_timezone()
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=tz)
    end_dt = datetime.combine(end_inclusive + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    country = (request.query_params.get("country") or "").upper()
    return queries.Range(start=start_dt, end=end_dt, country=country), None


class ReportView(AdminAuditMixin, APIView):
    """`GET /api/v1/admin/reports/{name}/` — the aggregate as JSON.

    NOT read-audited on screen: these are sums over orders, not a list of customers, and
    the project's line is drawn at bulk egress and personal data. The one report that
    names customers is audited when EXPORTED, below.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("reports.view")]
    audit_model_label = "orders.order"

    def get(self, request, name: str):
        fn = REPORTS.get(name)
        if fn is None:
            return Response({"detail": f"No report named {name!r}."}, status=404)
        window, error = _parse_window(request)
        if error:
            return Response({"detail": error}, status=400)

        rows = fn(window)
        return Response({
            "report": name,
            "start": window.start.date(),
            "end": (window.end - timedelta(days=1)).date(),
            "country": window.country,
            "rows": rows,
        })


class ReportExportView(AdminAuditMixin, APIView):
    """`GET /api/v1/admin/reports/{name}/export.csv`.

    READ-AUDITED, and gated above the on-screen report when the rows name customers —
    both by the precedent `AdminOrderCSVExportView` set. CSV rather than the spec's
    openpyxl-to-S3 job: Excel opens CSV, and a signed bucket link is an export that
    escapes both the scope check and this audit row.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("reports.view")]
    audit_action = "export_csv"
    audit_model_label = "orders.order"
    audit_reads = True

    def get(self, request, name: str):
        fn = REPORTS.get(name)
        if fn is None:
            return Response({"detail": f"No report named {name!r}."}, status=404)
        if name in CUSTOMER_NAMING and "orders.manage" not in scopes_for_user(request.user):
            return Response(
                {"detail": "Exporting a report that names customers requires orders.manage."},
                status=403,
            )
        window, error = _parse_window(request)
        if error:
            return Response({"detail": error}, status=400)

        rows = fn(window)
        response = StreamingHttpResponse(stream_csv(rows), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{name}.csv"'
        return response
