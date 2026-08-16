"""The admin payout queue.

Everything here is a thin HTTP wrapper. Every state change goes through
`apps.referrals.services`, which already owns the hard parts — the row locking, the
release-on-reject that un-strands a referrer's money, the recompute that applies a refund
which landed during the review window. A view that reached past those and updated a
status directly would silently skip all of it, so none of them do.

── WHY THE READS ARE AUDITED ────────────────────────────────────────────────────────

`audit_reads = True` on the queue, which most admin lists do not set. This one publishes
unmasked bank account numbers — it is the only screen in the product that does. If an
account number ever turns up somewhere it should not, the question "who looked at it, and
when" needs an answer, and the only place that answer can come from is a row written at
read time. Same reasoning as the product CSV export, applied to something worth more.

── THE THREE SCOPES ─────────────────────────────────────────────────────────────────

`referrals.view` reads the queue. `referrals.manage` approves, rejects. `referrals.pay`
marks a request PAID and is held by Owner AND Manager — Hammed's ruling of 2026-08-15,
recorded in `accounts/rbac.py`: the Manager runs the monthly transfers, and withholding
the scope would just get the Owner's login borrowed. It is still the one action
asserting cash left the company account, and nothing downstream ever re-checks it.
"""
from django.db.models import Case, IntegerField, Prefetch, Value, When
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, status, viewsets
from rest_framework.generics import ListAPIView
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.core.audit import AdminAuditMixin
from apps.referrals import services
from apps.referrals.admin_serializers import (
    AdjustmentRowSerializer,
    AdjustmentSerializer,
    ApprovePayoutSerializer,
    BlockReferrerSerializer,
    MarkPaidSerializer,
    PayoutCommissionSerializer,
    PayoutQueueSerializer,
    RejectPayoutSerializer,
    ReferrerSerializer,
)
from apps.core.models import Currency
from apps.referrals.models import (
    Commission,
    PayoutRequest,
    ReferralAdjustment,
    ReferralProfile,
)
from apps.referrals.views import _Page as ReferralPagination


def _referral_error(exc: services.ReferralError) -> Response:
    """Same shape the storefront gets: a stable code plus a human sentence.
    `payout_not_open` (409) is what two staff clicking Approve on the same row at the
    same time produces; the admin surfaces `detail` beside the button and re-reads the
    queue so the loser sees the row's real state."""
    return Response({"error": exc.code, "detail": exc.detail}, status=exc.http)


class PayoutQueueViewSet(AdminAuditMixin, viewsets.ReadOnlyModelViewSet):
    """`GET /api/v1/admin/referral-payouts/` and the three actions on a row.

    Default ordering is OLDEST REQUESTED FIRST, not newest. A payout queue is a work
    queue: the interesting row is the one that has been waiting longest, and a
    newest-first list buries it exactly as it becomes urgent. `days_open` rides along on
    every open row so the UI can shout about it without a second query.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("referrals.view")]
    serializer_class = PayoutQueueSerializer
    pagination_class = ReferralPagination
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["status", "currency"]
    search_fields = ["referrer__email", "referrer__toke_id", "reference"]
    # Reading this list means reading bank account numbers. See the module docstring.
    audit_reads = True
    audit_model_label = "referrals.payoutrequest"

    def get_queryset(self):
        return (
            PayoutRequest.objects.select_related("currency", "referrer", "decided_by")
            .prefetch_related(
                "referrer__referral_profile",
                "referrer__addresses",
                Prefetch(
                    "commissions",
                    queryset=Commission.objects.select_related("order").order_by("-created_at"),
                ),
            )
            # WORK FIRST, THEN HISTORY — and explicitly, because ordering by the status
            # COLUMN sorts it alphabetically: approved, paid, rejected, requested. That
            # puts the one status that needs a human dead last, which is the exact
            # opposite of what a queue is for. Caught on screen, not in a test.
            .annotate(
                queue_rank=Case(
                    When(status="requested", then=Value(0)),
                    When(status="approved", then=Value(1)),
                    default=Value(2),
                    output_field=IntegerField(),
                )
            )
            # Oldest first inside each group: the longest wait is the most urgent.
            .order_by("queue_rank", "created_at")
        )

    @action(detail=True, methods=["get"], url_path="commissions")
    def commissions(self, request, pk=None):
        """The orders this payout is made of. Separate from the row so the list stays
        one query per page rather than one per row."""
        payout = self.get_object()
        return Response(
            PayoutCommissionSerializer(payout.commissions.all(), many=True).data
        )


# ── THE WRITES LIVE ON THEIR OWN CLASSES ─────────────────────────────────────────────
#
# Not as `@action`s on the viewset above, and the reason is a guard rather than taste:
# `test_admin_surface_guard.py::test_nothing_named_view_is_routed_onto_a_writing_method`
# refuses to let a scope named `.view` be routed onto a POST. It cannot see that an
# `@action` elevates its own permission — it reads the URLconf, which is the right thing
# to read, because "what can this scope reach" is a property of the routes and not of a
# decorator somebody might delete. Splitting them means each action's scope is declared
# on the class that serves it and shows up in ADMIN_SURFACE as its own line.


class _PayoutActionView(AdminAuditMixin, APIView):
    """Shared plumbing: load the request, validate a body, call one service, return the
    row in the same shape the queue list uses so the admin UI can swap it in place."""

    authentication_classes = [AdminJWTAuthentication]
    body_serializer: type[serializers.Serializer]
    # Explicit, because these are APIViews with no queryset and no ModelSerializer for the
    # label to be derived from — and an audit row with no model label is a row nobody can
    # search for, which on a money action is the row you most need to find.
    audit_model_label = "referrals.payoutrequest"

    def act(self, request, pk: int, data: dict):  # pragma: no cover - interface
        raise NotImplementedError

    def post(self, request, pk: int):
        body = self.body_serializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            payout = self.act(request, pk, body.validated_data)
        except PayoutRequest.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except services.ReferralError as exc:
            return _referral_error(exc)
        return Response(PayoutQueueSerializer(payout).data)


class ApprovePayoutView(_PayoutActionView):
    """`referrals.manage` — staff mean to send this.

    Optional in a one-person shop: `mark_payout_paid` accepts a `requested` row directly,
    so Hammed can go straight to paid. Approve earns its keep when the person who checks
    the fraud flags is not the person who opens the banking app.
    """

    permission_classes = [HasAdminScope("referrals.manage")]
    body_serializer = ApprovePayoutSerializer
    # Named rather than left to default: an audit row for a money action has to be
    # findable by what it DID, not by an HTTP verb.
    audit_action = "payout_approve"

    def act(self, request, pk, data):
        return services.approve_payout(
            pk, staff_user=request.user, admin_note=data.get("admin_note", ""),
        )


class RejectPayoutView(_PayoutActionView):
    """`referrals.manage` — refuse it and RELEASE the commissions back to available.

    Rejection is reversible by design and that is the whole point: a refused request that
    kept its commissions claimed would read as a zero balance forever with no row
    explaining it. Accepts an `approved` row too, for a transfer the bank bounced.
    """

    permission_classes = [HasAdminScope("referrals.manage")]
    body_serializer = RejectPayoutSerializer
    # Named rather than left to default: an audit row for a money action has to be
    # findable by what it DID, not by an HTTP verb.
    audit_action = "payout_reject"

    def act(self, request, pk, data):
        return services.reject_payout(
            pk, staff_user=request.user,
            customer_message=data["customer_message"],
            admin_note=data.get("admin_note", ""),
        )


class MarkPayoutPaidView(_PayoutActionView):
    """`referrals.pay` (Owner + Manager — see the module docstring). The transfer left
    the bank.

    The one action in the programme that asserts cash has actually moved, and nothing
    downstream re-checks it. The bank's reference is required (the service refuses
    without one): it is the only artefact that answers "I never received it". Sends the
    customer their payout email.
    """

    permission_classes = [HasAdminScope("referrals.pay")]
    body_serializer = MarkPaidSerializer
    # Named rather than left to default: an audit row for a money action has to be
    # findable by what it DID, not by an HTTP verb.
    audit_action = "payout_paid"

    def act(self, request, pk, data):
        return services.mark_payout_paid(
            pk, staff_user=request.user,
            reference=data["reference"],
            admin_note=data.get("admin_note", ""),
        )


# ── REFERRERS: THE ABUSE AND CORRECTION SURFACE ──────────────────────────────────────
#
# A separate screen from the payout queue on purpose. The queue answers "settle what
# people have asked for"; this answers "something is wrong with this person's account".
# Mixing them would mean the month-end payment pass, which is rushed by nature, is also
# where somebody reaches for the block button.


class ReferrerListView(AdminAuditMixin, ListAPIView):
    """`GET /admin/referrers/` — every customer with a referral profile.

    Read-audited for the same reason the payout queue is: the rows carry a customer's
    name, email and what they have earned. Not as expensive a read as a bank account
    number, but it is still a list of people and what they are worth.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("referrals.view")]
    serializer_class = ReferrerSerializer
    pagination_class = ReferralPagination
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["is_blocked"]
    search_fields = ["user__email", "user__toke_id", "code", "user__first_name", "user__last_name"]
    audit_reads = True
    audit_model_label = "referrals.referralprofile"

    def get_queryset(self):
        return ReferralProfile.objects.select_related("user").order_by(
            # Blocked first: if somebody opens this screen without searching, it is
            # usually to see who is currently stopped and why.
            "-is_blocked", "-created_at",
        )


class ReferrerAdjustmentsView(AdminAuditMixin, ListAPIView):
    """`GET /admin/referrers/<pk>/adjustments/` — what has already been done by hand."""

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("referrals.view")]
    serializer_class = AdjustmentRowSerializer
    pagination_class = ReferralPagination
    audit_reads = True
    audit_model_label = "referrals.referraladjustment"

    def get_queryset(self):
        return (
            ReferralAdjustment.objects.select_related("currency", "created_by")
            .filter(referrer_id=self.kwargs["pk"])
            .order_by("-created_at")
        )


class BlockReferrerView(AdminAuditMixin, APIView):
    """`referrals.manage` — stop or resume a referrer earning.

    Does not touch money already earned and does not decide an open payout request; see
    `services.set_referrer_blocked` for why both restraints are deliberate.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("referrals.manage")]
    audit_action = "referrer_block"
    audit_model_label = "referrals.referralprofile"

    def post(self, request, pk: int):
        body = BlockReferrerSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        profile = ReferralProfile.objects.select_related("user").filter(user_id=pk).first()
        if profile is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            profile = services.set_referrer_blocked(
                profile.user,
                blocked=body.validated_data["blocked"],
                reason=body.validated_data.get("reason", ""),
                staff_user=request.user,
            )
        except services.ReferralError as exc:
            return _referral_error(exc)
        return Response(ReferrerSerializer(profile).data)


class CreateAdjustmentView(AdminAuditMixin, APIView):
    """`referrals.manage` — move a balance by hand, with a reason that outlives everyone.

    The amount is signed and the service refuses very little on purpose (see
    `services.add_adjustment`): this is the escape hatch for cases the model did not
    anticipate, and validation that second-guesses the human defeats the point.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("referrals.manage")]
    audit_action = "referral_adjustment"
    audit_model_label = "referrals.referraladjustment"

    def post(self, request, pk: int):
        body = AdjustmentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        profile = ReferralProfile.objects.select_related("user").filter(user_id=pk).first()
        if profile is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        currency = Currency.objects.filter(code=body.validated_data["currency"].upper()).first()
        if currency is None:
            return Response({"error": "unknown_currency", "detail": "No such currency."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            adjustment = services.add_adjustment(
                profile.user,
                currency=currency,
                amount=body.validated_data["amount"],
                kind=body.validated_data["kind"],
                reason=body.validated_data["reason"],
                staff_user=request.user,
            )
        except services.ReferralError as exc:
            return _referral_error(exc)
        return Response(AdjustmentRowSerializer(adjustment).data, status=status.HTTP_201_CREATED)
