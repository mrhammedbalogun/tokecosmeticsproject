"""The Marketing screen's endpoints.

`settings.manage`, which is Owner-only, and the same reasoning `rbac.py` already applies
to the payout bank account. Two of the things on this screen justify it:

  * `consent_required_countries` decides whose consent is asked for before a tracking
    cookie is set. That is a legal position, like the tax screens next door, not an
    operational knob.
  * a pixel id decides which ad account receives the shop's customer data. Pointing it
    at the wrong dataset does not break anything visibly — it just sends the customer
    list somewhere else.

The outbox list is read-only and audited on READ, because its `payload` column carries
hashed customer identifiers and, for Meta, a raw IP address and user agent.
"""
from __future__ import annotations

from django.db.models import Q
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.core.audit import AdminAuditMixin
from apps.marketing.admin_serializers import (
    ConversionEventAdminSerializer,
    MarketingChannelAdminSerializer,
    MarketingSettingsAdminSerializer,
)
from apps.marketing.models import (
    CHANNEL_CHOICES, ConversionEvent, MarketingChannel, MarketingSettings,
)


def ensure_channel_rows() -> None:
    """Every platform the code has an adapter for gets a row, created on first read.

    A seed migration was the alternative and it loses to this: a migration seeds the
    channels that existed the day it was written, so adding a fifth platform later means
    remembering to write a second data migration, and forgetting means the screen simply
    does not show the new channel. Creating on read cannot drift from `CHANNEL_CHOICES`.
    """
    existing = set(MarketingChannel.objects.values_list("code", flat=True))
    missing = [MarketingChannel(code=code) for code, _ in CHANNEL_CHOICES if code not in existing]
    if missing:
        MarketingChannel.objects.bulk_create(missing, ignore_conflicts=True)


class MarketingSettingsView(AdminAuditMixin, generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/admin/marketing/settings/ — the master switch and the policy.

    A singleton `MarketingSettings.load()` creates on first touch, so there is no 404
    arm, exactly like the tax and business-decision screens.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("settings.manage")]
    serializer_class = MarketingSettingsAdminSerializer
    audit_serializers = (MarketingSettingsAdminSerializer,)

    def get_object(self):
        return MarketingSettings.load()


class MarketingChannelAdminViewSet(
    AdminAuditMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """GET/PATCH /api/v1/admin/marketing/channels/[{code}/] — one row per platform.

    No create, no delete: the row set IS the adapter set. Looked up by `code` rather
    than by primary key so the URL reads `/channels/meta/` and a screen never has to
    learn an integer to talk about Facebook.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("settings.manage")]
    serializer_class = MarketingChannelAdminSerializer
    audit_serializers = (MarketingChannelAdminSerializer,)
    lookup_field = "code"
    pagination_class = None  # five rows; a pager would be theatre
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        ensure_channel_rows()
        return MarketingChannel.objects.all()

    @action(detail=True, methods=["post"], url_path="test-event")
    def test_event(self, request, code=None):
        """POST .../channels/{code}/test-event/ — prove the credentials actually work.

        ── WHY THIS BUTTON EXISTS ──────────────────────────────────────────────────────

        None of these four APIs can be exercised without a real ad account, so nothing
        in the test suite can tell Hammed that the token he pasted into `.env.prod` is
        the right one. Every failure mode up to that point is silent: a wrong pixel id
        is accepted, a revoked token is accepted by the transport and refused by the
        envelope, and a channel that has never worked looks exactly like a channel with
        no sales yet.

        The event is sent with the channel's `test_event_code` when one is set, which is
        what keeps it out of the live dataset. WITHOUT one it lands in the real dataset
        as a genuine £0/₦0 purchase — the response says so rather than refusing, because
        Snapchat has no test mode at all and refusing would make this button useless for
        the one platform that most needs proving.
        """
        channel_row = self.get_object()
        from apps.marketing.channels.registry import build_channel
        from apps.marketing.credentials import missing_settings_for
        from apps.marketing.testing import test_payload

        missing = missing_settings_for(channel_row.code)
        if missing:
            return Response(
                {"ok": False, "error": "missing_credential", "missing_settings": missing},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not channel_row.pixel_id:
            return Response({"ok": False, "error": "no_pixel_id"},
                            status=status.HTTP_400_BAD_REQUEST)

        channel = build_channel(channel_row)
        if channel is None:
            return Response({"ok": False, "error": "no_server_side_sender"},
                            status=status.HTTP_400_BAD_REQUEST)

        # Google alone has no test console. Its "test event" is therefore a
        # `validateOnly` call — Google checks the request in full and records nothing —
        # because a landed test would be a real zero-value purchase in a LIVE conversion
        # action, which is the one thing this button must not do.
        if getattr(channel, "validate_only", None) is False:
            channel.validate_only = True

        # A SHORT budget, because this call happens inside the audit mixin's transaction
        # (see `ConversionChannel.send`). A vendor that is down should answer the Owner in
        # six seconds, not hold a database connection open for twenty.
        result = channel.send(channel.build(test_payload()), timeout=6.0, retries=0)
        validated_only = bool(getattr(channel, "validate_only", False))
        return Response({
            "ok": result.ok,
            "status": result.status,
            "response": result.excerpt[:500],
            # Said out loud in the response so the screen can warn: this one landed in
            # the live dataset. Google is never live — it validates instead.
            "used_test_event_code": bool(channel_row.test_event_code) or validated_only,
            "validated_only": validated_only,
        })


class ConversionEventAdminViewSet(
    AdminAuditMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """GET /api/v1/admin/marketing/events/ — the outbox, newest first.

    `audit_reads = True`: the `payload` column carries hashed customer identifiers and,
    for Meta, a raw IP and user agent. Reading it is a PII read and the audit table says
    so, the same way the customer screens do.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("settings.manage")]
    serializer_class = ConversionEventAdminSerializer
    audit_reads = True
    audit_model_label = "marketing.conversionevent"

    def get_queryset(self):
        qs = ConversionEvent.objects.select_related("order").all()
        channel = self.request.query_params.get("channel", "")
        state = self.request.query_params.get("status", "")
        search = self.request.query_params.get("search", "").strip()
        if channel:
            qs = qs.filter(channel=channel)
        if state:
            qs = qs.filter(status=state)
        if search:
            qs = qs.filter(Q(event_id__icontains=search) | Q(order__number__icontains=search))
        return qs
