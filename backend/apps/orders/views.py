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
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.invoice import render_invoice_pdf
from apps.orders.models import Order
from apps.orders.services import cancel_order
from apps.orders.serializers import (
    AdminOrderListSerializer,
    AdminOrderSerializer,
    OrderListSerializer,
    OrderSerializer,
    OrderTrackingSerializer,
)
from apps.orders.state import IllegalTransition, record_event, resolve_review, transition_by_id
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


class AdminOrderListView(generics.ListAPIView):
    """GET /api/v1/admin/orders/ — filters: status, country, source, needs_attention,
    placed_after/placed_before, gateway, search (number / email / name)."""

    serializer_class = AdminOrderListSerializer
    permission_classes = [permissions.IsAdminUser]  # PLAN-16: fine-grained RBAC

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


class AdminOrderDetailView(generics.RetrieveAPIView):
    serializer_class = AdminOrderSerializer
    permission_classes = [permissions.IsAdminUser]
    lookup_field = "number"
    queryset = _ORDER_QS.prefetch_related("events", "events__actor")


class AdminOrderTransitionView(APIView):
    """POST /api/v1/admin/orders/{number}/transition/ — body: {to_status, message?}."""

    permission_classes = [permissions.IsAdminUser]

    def post(self, request, number: str):
        order = get_object_or_404(Order, number=number)
        to_status = request.data.get("to_status")
        if not to_status:
            return Response({"error": "to_status_required"}, status=400)
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


class AdminOrderTrackingView(APIView):
    """PATCH /api/v1/admin/orders/{number}/tracking/ — set carrier + number.

    Only records the tracking details. The customer is told when the order is moved to
    `shipped`, which is what fires the email — so set tracking first, then ship.
    """

    permission_classes = [permissions.IsAdminUser]

    def patch(self, request, number: str):
        order = get_object_or_404(Order, number=number)
        order.tracking_carrier = request.data.get("tracking_carrier", order.tracking_carrier)
        order.tracking_number = request.data.get("tracking_number", order.tracking_number)
        order.save(update_fields=["tracking_carrier", "tracking_number", "updated_at"])
        record_event(order, "tracking", actor=request.user,
                     message=f"{order.tracking_carrier} {order.tracking_number}".strip())
        return Response(AdminOrderSerializer(order).data)


class AdminOrderNoteView(APIView):
    """PATCH /api/v1/admin/orders/{number}/note/ — internal note, never shown to the
    customer and never a status change."""

    permission_classes = [permissions.IsAdminUser]

    def patch(self, request, number: str):
        order = get_object_or_404(Order, number=number)
        order.admin_note = request.data.get("admin_note", "")
        order.save(update_fields=["admin_note", "updated_at"])
        record_event(order, "note", actor=request.user, message=order.admin_note)
        return Response(AdminOrderSerializer(order).data)


class AdminResolveReviewView(APIView):
    """POST /api/v1/admin/orders/{number}/resolve-review/ — clear the needs-attention flag.

    The ONLY thing that clears review_reason. Deliberately not a side-effect of any status
    change: shipping a double-payment order must not erase the reason someone still owes
    the customer a refund.
    """

    permission_classes = [permissions.IsAdminUser]

    def post(self, request, number: str):
        order = get_object_or_404(Order, number=number)
        resolve_review(order.pk, actor=request.user, message=request.data.get("message", ""))
        order.refresh_from_db()
        return Response(AdminOrderSerializer(order).data)
