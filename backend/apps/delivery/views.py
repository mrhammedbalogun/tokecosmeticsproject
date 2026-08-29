import logging
import secrets

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


class AajWebhookThrottle(CloudflareIdentMixin, SimpleRateThrottle):
    """Same reasoning as GIG's: generous, because the path token is the real gate
    and a throttled webhook is a retried webhook."""

    scope = "aaj_webhook"
    rate = "600/min"

    def get_cache_key(self, request, view):
        return f"webhook:aaj:{client_ip(request)}"


class AajWebhookView(APIView):
    """POST /api/v1/webhooks/aaj/<token>/ — AAJ tracking events (aaj/webhook.py has
    the scheme, and the reasons it has to be tolerant).

    No auth class: the token in the path is the credential, exactly as a gateway
    signature is for payment webhooks. A signature header, if AAJ sends one, must
    also verify — see verify_signature.
    """

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AajWebhookThrottle]

    def post(self, request, token: str):
        from apps.delivery.aaj import webhook as aaj_webhook

        expected = settings.AAJ_WEBHOOK_TOKEN
        if not expected:
            # Not configured yet — 503 keeps AAJ retrying and makes the gap visible
            # rather than silently eating events (GIG's receiver reasons the same).
            logger.error("aaj webhook hit but AAJ_WEBHOOK_TOKEN is unset")
            return Response({"error": "webhook_not_configured"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not secrets.compare_digest(token, expected):
            logger.warning("Rejected aaj webhook: bad path token from %s", client_ip(request))
            return Response({"error": "unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

        headers = {k: v for k, v in request.headers.items()}
        verified, how = aaj_webhook.verify_signature(
            request.body, headers, settings.AAJ_WEBHOOK_SIGNING_KEY
        )
        if not verified and "no signature header" not in how:
            # They signed it and we could not reproduce it. Holding the URL is not a
            # licence to skip a check they performed.
            logger.warning("Rejected aaj webhook: %s", how)
            return Response({"error": "bad_signature"}, status=status.HTTP_401_UNAUTHORIZED)
        # The line that turns their undocumented scheme into a pinned one.
        logger.info("aaj webhook accepted (%s)", how)

        try:
            payload = aaj_webhook.parse_body(request.body)
        except aaj_webhook.InvalidWebhookPayload as exc:
            logger.warning("Rejected aaj webhook: %s", exc)
            return Response({"error": "invalid_payload"}, status=status.HTTP_400_BAD_REQUEST)

        outcome = aaj_webhook.apply_event(payload, timezone.now())
        return Response({"status": "success", "outcome": outcome})
