"""Order APIs — customer-facing and admin.

Access rules, and why:

- A customer's queryset is filtered to `user=request.user`, so a stranger's order 404s
  rather than 403s. A 403 confirms the order exists, which is a free oracle for probing
  order numbers.
- The tracking token names its own order; the URL's number is checked AGAINST it, never
  trusted. See orders/tokens.py.
- The invoice is owner-only and does NOT accept a tracking token: it carries name,
  address and billing details, strictly more than the redacted tracking view.
"""
from django.db.models import Q
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope, scopes_for_user
from apps.core.audit import AdminAuditMixin
from apps.orders.invoice import render_invoice_pdf
from apps.orders.models import Order
from apps.orders.services import cancel_order, orders_owed_a_refund
from apps.orders.serializers import (
    AdminOrderListSerializer,
    AdminOrderSerializer,
    OrderListSerializer,
    OrderSerializer,
    OrderTrackingSerializer,
    RefundOwedSerializer,
)
from apps.orders.csv_io import export_orders_csv
from apps.orders.state import (
    ELEVATED_STATUSES,
    IllegalTransition,
    record_event,
    resolve_review,
    transition_by_id,
)
from apps.orders.tokens import TrackingTokenError, read_tracking_token

_ORDER_QS = Order.objects.select_related("currency", "country").prefetch_related("items")


class OrderListView(generics.ListAPIView):
    """GET /api/v1/orders/ — the caller's own orders."""

    serializer_class = OrderListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return _ORDER_QS.filter(user=self.request.user).order_by("-placed_at", "-pk")


class OrderDetailView(APIView):
    """GET /api/v1/orders/{number}/ — the owner, or a holder of the signed tracking link.

    Token holders get the REDACTED serializer. Deliberately open to anonymous callers,
    but only with a valid token for the order named in the URL.
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request, number: str):
        token = request.query_params.get("token")
        if token:
            try:
                signed_number = read_tracking_token(token)
            except TrackingTokenError:
                return Response({"error": "invalid_token"}, status=status.HTTP_404_NOT_FOUND)
            # The token names the order; the URL does not get a vote.
            if signed_number != number:
                return Response({"error": "invalid_token"}, status=status.HTTP_404_NOT_FOUND)
            order = get_object_or_404(_ORDER_QS, number=number)
            return Response(OrderTrackingSerializer(order).data)

        if not request.user.is_authenticated:
            return Response({"error": "authentication_required"},
                            status=status.HTTP_403_FORBIDDEN)
        # Filtered by owner, so someone else's order 404s instead of confirming it exists.
        order = get_object_or_404(_ORDER_QS, number=number, user=request.user)
        return Response(OrderSerializer(order).data)


class OrderInvoiceView(APIView):
    """GET /api/v1/orders/{number}/invoice.pdf — owner only, rendered on demand.

    No token path: an invoice carries the customer's name, address and billing details.
    If guest invoices are ever needed, mint a separate invoice-scoped token — do not
    widen the tracking one.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, number: str):
        qs = _ORDER_QS if request.user.is_staff else _ORDER_QS.filter(user=request.user)
        order = get_object_or_404(qs, number=number)
        pdf = render_invoice_pdf(order)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{order.number}.pdf"'
        return resp


# --- admin ------------------------------------------------------------------
#
# SCOPES, and the axis they are chosen on. Plan-16 Amendment 7 splits the order surface
# three ways, and the line is MONEY, not HTTP verb:
#
# * `orders.view`    — reading the queue and one order. Carries the customer's email and
#                      address, which is why Support holds it: answering "where is my
#                      order?" is the job. It is not a lower-sensitivity scope, it is a
#                      non-writing one.
# * `orders.operate` — the Support day job. Ship it, track it, note it. Changes state,
#                      cannot move a naira.
# * `orders.manage`  — anything that moves money or destroys the record that money is
#                      owed. Owner and Manager only.
#
# Two of the assignments below are judgement calls rather than readings of the
# amendment, and both are argued at their view.


class AdminOrderListView(AdminAuditMixin, generics.ListAPIView):
    """GET /api/v1/admin/orders/ — filters: status, country, source, needs_attention,
    placed_after/placed_before, gateway, search (number / email / name)."""

    serializer_class = AdminOrderListSerializer
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.view")]
    # READ-AUDITED. Every row this returns carries a customer email and a shipping
    # address, and the `search` parameter is the interesting half of the record: "listed
    # every order matching @gmail.com, 3,400 results" is precisely the sentence an audit
    # log exists to be able to write, and it is invisible in a log of writes only.
    audit_reads = True
    audit_action = "list"

    def get_queryset(self):
        qs = _ORDER_QS.all()
        p = self.request.query_params
        if v := p.get("status"):
            qs = qs.filter(status=v)
        if v := p.get("country"):
            qs = qs.filter(country_id=v)
        if v := p.get("source"):
            qs = qs.filter(source=v)
        if v := p.get("gateway"):
            qs = qs.filter(payments__gateway=v)
        if v := p.get("placed_after"):
            qs = qs.filter(placed_at__gte=v)
        if v := p.get("placed_before"):
            qs = qs.filter(placed_at__lte=v)
        if p.get("needs_attention") == "true":
            # review_reason is the single source of truth — there is no needs_review
            # status to also check. See orders/models.py.
            qs = qs.exclude(review_reason="")
        if v := p.get("search"):
            qs = qs.filter(
                Q(number__icontains=v)
                | Q(legacy_number__icontains=v)
                | Q(email__icontains=v)
                | Q(shipping_address__icontains=v)
            )
        return qs.order_by("-placed_at", "-pk").distinct()


class AdminRefundsOwedView(AdminAuditMixin, generics.ListAPIView):
    """GET /api/v1/admin/refunds-owed/ — orders parked at on_hold by a cancelled freight
    quote, where the customer paid and is still owed a manual goods refund. The reminder
    that stops a solo operator forgetting the refund cancel_quote deliberately deferred.
    See apps/orders/services.orders_owed_a_refund for the predicate and its rationale.

    JUDGEMENT CALL: `orders.manage`, not `orders.view`, despite being a pure GET. The
    naming rule only forbids a `.view` scope that writes; it does not require every read
    to be `.view`. This endpoint is not a view of orders, it is a WORKLIST for one
    specific money operation — its rows exist solely to be actioned by issuing a refund,
    which is `orders.manage`. Handing it to Support produces a queue they can read and
    cannot clear, and the predictable result is not "Support helpfully escalates" but
    "two people believe the other is watching the list". Pair the worklist with the
    action. Support can still see any individual order and its payments through
    `orders.view`, so nothing is hidden from them — only the reminder is targeted."""

    serializer_class = RefundOwedSerializer
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.manage")]
    audit_reads = True  # a list of orders, with the customer on each one
    audit_action = "list"

    def get_queryset(self):
        return orders_owed_a_refund().select_related("currency", "shipping_quote").prefetch_related(
            "payments__refunds"
        )


class AdminOrderDetailView(AdminAuditMixin, generics.RetrieveAPIView):
    serializer_class = AdminOrderSerializer
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.view")]
    audit_reads = True  # name, email, phone, both addresses, payment history
    audit_action = "read"
    lookup_field = "number"
    queryset = _ORDER_QS.prefetch_related("events", "events__actor")


def _refund_owned_by_the_ledger(order) -> bool:
    """Whether this order still holds money that a real refund would have to move.

    True when any payment is `succeeded` (captured, untouched) or `partially_refunded`
    (some returned, the rest still held). In both cases marking the order `refunded` by
    hand would end it while the customer is still owed money — so the refund machinery
    owns that move and this endpoint must refuse it.

    False when there are no payments at all, or every payment is already `refunded`,
    `failed`, `cancelled`, `initiated` or `pending`. That covers the legacy-triage case
    Plan-23 needs — an order refunded in WooCommerce has no captured payment here — and
    the tidy-up case where the ledger settled but the lifecycle never caught up.
    """
    return order.payments.filter(status__in=("succeeded", "partially_refunded")).exists()


class AdminOrderTransitionView(AdminAuditMixin, APIView):
    """POST /api/v1/admin/orders/{number}/transition/ — body: {to_status, message?}.

    THE ONE ROUTE THAT SPANS TWO SCOPES, and the reason is the dispatch below rather
    than anything about permissions. Amendment 7 puts status transitions on
    `orders.operate` (Support's day job: ship it, deliver it) and cancellation on
    `orders.manage` (money). Both arrive here, as different values of `to_status`.

    Neither single scope is honest. `orders.manage` on the whole endpoint takes shipping
    away from Support, which is the exact job `orders.operate` was created to describe.
    `orders.operate` on the whole endpoint lets Support cancel — freeing the stock
    reservation and, on a paid order, leaving a customer who has been charged with a
    cancelled order and no refund.

    So the declared `permission_classes` is the FLOOR, and cancelling elevates. The check
    is written inline rather than in `get_permissions()` deliberately: overriding
    `get_permissions` would make the class attribute decorative, and that attribute is
    what `test_admin_surface_guard.py` reads to prove the whole admin surface is bound to
    a scope. A guard that inspects a lie is worse than no guard. The cost is that the
    elevation is invisible to the guard — paid for by
    `test_admin_role_matrix.py::test_support_cannot_issue_a_refund_but_can_ship`, which
    drives it over real HTTP.

    If a second status ever needs elevating, split the route instead of growing this set.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.operate")]
    # `to_status` is the whole point of the row: the elevation to orders.manage for a
    # cancel is invisible to the surface guard (see above), so the audit trail is where
    # "who cancelled a paid order" is actually answerable after the fact.
    audit_action = "transition"
    audit_model_label = "orders.order"
    audit_allowlist = ("to_status", "message")

    # Statuses that cost money to enter, and the scope each demands on top of the floor.
    # `refunded` joined `cancelled` here after a Plan-18 review found it reachable by
    # anyone holding `orders.operate`: it is a legal destination from `processing`,
    # `shipped`, `delivered` and `completed` (state.py), and every one of those fell
    # through to `transition_by_id` — a bare status flip with no Refund row, no money
    # moved and no restock, leaving the order terminal and out of the pipeline. Audited,
    # so the trail recorded a refund that never happened.
    #
    # Scope alone is NOT the fix, because a Manager clicking it would do the same damage
    # with better credentials. See `_refund_owned_by_the_ledger` below.
    # Imported from `state` so the admin serializer can publish the same rule this
    # enforces (Plan-18a). Kept as a class attribute because that is what the
    # elevation is read off in tests and in the guard walkers.
    ELEVATED_STATUSES = ELEVATED_STATUSES

    def post(self, request, number: str):
        to_status = request.data.get("to_status")
        # Checked BEFORE the order lookup so an unauthorised caller gets a clean 403
        # rather than a 404 that quietly tells them whether the order exists.
        required = self.ELEVATED_STATUSES.get(to_status)
        if required and required not in scopes_for_user(request.user):
            raise exceptions.PermissionDenied(
                f"Moving an order to {to_status!r} requires the {required} scope."
            )
        order = get_object_or_404(Order, number=number)
        if not to_status:
            return Response({"error": "to_status_required"}, status=400)
        if to_status == "refunded" and _refund_owned_by_the_ledger(order):
            # Deliberately NOT a blanket refusal. `on_hold` is the triage state for the 879
            # legacy orders Plan-23 migrates, and one refunded in WooCommerce years ago has
            # no captured payment here and no money to move — recording it is history. The
            # line is drawn by the LEDGER, not by the status.
            return Response(
                {
                    "error": "refund_required",
                    "detail": (
                        "This order still holds captured payment, so it cannot be marked "
                        "refunded by hand — that would end the order without moving any "
                        "money or restocking. Use the refund endpoint instead."
                    ),
                },
                status=400,
            )
        # Cancelling is NOT a bare status flip: it must free the reservation atomically
        # with the move, and cancel_order is the only thing that does. Routing it through
        # transition_by_id would cancel the order and hold its stock forever —
        # expire_pending_orders sweeps `pending_payment` only, so nothing would ever
        # reclaim it. Any status with a mandatory side-effect belongs in this dispatch.
        mover = cancel_order if to_status == "cancelled" else None
        try:
            if mover:
                mover(order.pk, actor=request.user, message=request.data.get("message", ""))
            else:
                # transition_by_id re-reads under the row lock, so this validates against
                # the CURRENT status even if a webhook moved it since the page loaded.
                transition_by_id(order.pk, to_status, actor=request.user,
                                 message=request.data.get("message", ""))
        except IllegalTransition as exc:
            return Response({"error": "illegal_transition", "detail": str(exc)}, status=400)
        order.refresh_from_db()
        return Response(AdminOrderSerializer(order).data)


class AdminOrderTrackingView(AdminAuditMixin, APIView):
    """PATCH /api/v1/admin/orders/{number}/tracking/ — set carrier + number.

    Only records the tracking details. The customer is told when the order is moved to
    `shipped`, which is what fires the email — so set tracking first, then ship.

    `orders.operate`: it writes, but the write is a carrier and a consignment number.
    Nothing here can move money, and recording tracking is half of what shipping means.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.operate")]
    audit_action = "tracking"
    audit_model_label = "orders.order"
    audit_allowlist = ("tracking_carrier", "tracking_number")

    def patch(self, request, number: str):
        order = get_object_or_404(Order, number=number)
        order.tracking_carrier = request.data.get("tracking_carrier", order.tracking_carrier)
        order.tracking_number = request.data.get("tracking_number", order.tracking_number)
        order.save(update_fields=["tracking_carrier", "tracking_number", "updated_at"])
        record_event(order, "tracking", actor=request.user,
                     message=f"{order.tracking_carrier} {order.tracking_number}".strip())
        return Response(AdminOrderSerializer(order).data)


class AdminOrderNoteView(AdminAuditMixin, APIView):
    """PATCH /api/v1/admin/orders/{number}/note/ — internal note, never shown to the
    customer and never a status change.

    `orders.operate`. Leaving a note is the record of a phone call, which is Support's
    work; the note is internal, so the worst case is an inaccurate internal record.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.operate")]
    audit_action = "note"
    audit_model_label = "orders.order"
    # The note itself is stored: it is an internal record of a phone call, written by
    # staff about the order, and it is already visible to everyone who can read the
    # order. Nothing is revealed by keeping a copy of what somebody typed here.
    audit_allowlist = ("admin_note",)

    def patch(self, request, number: str):
        order = get_object_or_404(Order, number=number)
        order.admin_note = request.data.get("admin_note", "")
        order.save(update_fields=["admin_note", "updated_at"])
        record_event(order, "note", actor=request.user, message=order.admin_note)
        return Response(AdminOrderSerializer(order).data)


class AdminResolveReviewView(AdminAuditMixin, APIView):
    """POST /api/v1/admin/orders/{number}/resolve-review/ — clear the needs-attention flag.

    The ONLY thing that clears review_reason. Deliberately not a side-effect of any status
    change: shipping a double-payment order must not erase the reason someone still owes
    the customer a refund.

    JUDGEMENT CALL: `orders.manage`, not `orders.operate`, even though clearing a flag
    moves no money. `review_reason` is precisely the marker that says money went wrong on
    this order — a double payment, a short RoW transfer, a refund still owed. Clearing it
    does not move a naira, it DESTROYS THE RECORD that one needs to move, and the
    docstring above already explains that nothing else may erase it. Judged on outcome
    rather than on mechanism, dismissing a money alarm belongs with the money scope: the
    person who clears it should be the person who could also settle it.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.manage")]
    # Clearing review_reason DESTROYS the record that money went wrong on this order
    # (see the docstring). The audit row is the only thing left saying it was ever set.
    audit_action = "resolve_review"
    audit_model_label = "orders.order"
    audit_allowlist = ("message",)

    def post(self, request, number: str):
        order = get_object_or_404(Order, number=number)
        resolve_review(order.pk, actor=request.user, message=request.data.get("message", ""))
        order.refresh_from_db()
        return Response(AdminOrderSerializer(order).data)


class AdminOrderCSVExportView(AdminAuditMixin, APIView):
    """GET /api/v1/admin/orders/export.csv — every order, as a file.

    `orders.manage`, a scope ABOVE the order list's `orders.view`. Support works the order
    desk all day and must read orders one at a time; a single file carrying every
    customer's email, country and totals is a different act. Same reasoning the catalogue
    export records: a whole-table dump is bulk egress whatever it contains, and this one
    contains personal data outright.

    Read-audited for the same reason.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.manage")]
    audit_reads = True
    audit_action = "export_csv"
    audit_model_label = "orders.order"

    def get(self, request):
        resp = StreamingHttpResponse(iter([export_orders_csv()]), content_type="text/csv")
        resp["Content-Disposition"] = "attachment; filename=orders.csv"
        return resp


class AdminOrderInvoiceView(AdminAuditMixin, APIView):
    """GET /api/v1/admin/orders/{number}/invoice.pdf — staff, and RECORDED.

    THIS ROUTE IS NOT ABOUT ACCESS. `OrderInvoiceView` on the customer surface already has
    a staff bypass, and `CustomerJWTAuthentication` deliberately accepts admin tokens — so
    the admin app could always fetch any customer's invoice. What it could not do is leave
    a trace: that route sits outside the admin prefix, where neither the surface guard nor
    the audit mixin reaches.

    An invoice carries the customer's name, home address and billing details. Plan-16's
    ruling audits PII-bearing reads, so the version staff actually use is the audited one.

    `orders.view`, not `.manage`: an invoice goes in the parcel, and packing is Support's
    job. One order at a time, and written down.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.view")]
    audit_reads = True
    audit_action = "read_invoice"
    audit_model_label = "orders.order"

    def get(self, request, number: str):
        order = get_object_or_404(_ORDER_QS, number=number)
        pdf = render_invoice_pdf(order)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{order.number}.pdf"'
        return resp
