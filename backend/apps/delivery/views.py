import logging

from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.accounts.throttling import CloudflareIdentMixin, client_ip
from apps.core.models import Region
from apps.delivery.gig.webhook import InvalidWebhookPayload, apply_event, decrypt_payload
from apps.delivery.serializers import RegionSerializer

logger = logging.getLogger(__name__)


class RegionBrowseView(ListAPIView):
    serializer_class = RegionSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None  # region lists are short and used to fill dropdowns

    def get_queryset(self):
        parent = self.request.query_params.get("parent")
        country = self.request.query_params.get("country")
        if parent:
            return Region.objects.filter(parent_id=parent, is_active=True).order_by("name")
        if country:
            return Region.objects.filter(
                country_code=country.upper(), parent__isnull=True, is_active=True
            ).order_by("name")
        raise ValidationError("Provide ?country=<CC> for states or ?parent=<id> for children.")


class GigWebhookThrottle(CloudflareIdentMixin, SimpleRateThrottle):
    """Mirror of payments' WebhookThrottle reasoning: generous, because GIG
    retries any non-2xx (429 included) and decryption is the real gate."""

    scope = "gig_webhook"
    rate = "600/min"

    def get_cache_key(self, request, view):
        return f"webhook:gig:{client_ip(request)}"


class GigWebhookView(APIView):
    """POST /api/v1/webhooks/gig/ — GIG tracking events (gig/webhook.py has the scheme).

    No auth: successful AES decryption with our registered secret IS the
    authentication, exactly as gateway signatures are for payment webhooks.
    """

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [GigWebhookThrottle]
    parser_classes: list = []  # the body is a bare base64 string, not JSON

    def post(self, request):
        secret = settings.GIG_WEBHOOK_SECRET
        if not secret:
            # Not registered yet (pre-go-live) — a 503 keeps GIG retrying and makes
            # the misconfiguration visible instead of silently eating events.
            logger.error("gig webhook hit but GIG_WEBHOOK_SECRET is unset")
            return Response({"error": "webhook_not_configured"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        body = request.body.decode("utf-8", errors="replace").strip().strip('"')
        try:
            event = decrypt_payload(body, secret)
        except InvalidWebhookPayload as exc:
            logger.warning("Rejected gig webhook: %s", exc)
            return Response({"error": "invalid_payload"}, status=status.HTTP_400_BAD_REQUEST)

        apply_event(event, timezone.now())
        # The docs' expected ack, verbatim — including for unknown waybills (see apply_event).
        return Response({"status": "success", "message": "Webhook received successfully"})
