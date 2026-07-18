from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.newsletter.models import NewsletterSubscriber
from apps.newsletter.serializers import SubscribeSerializer
from apps.newsletter.tokens import UnsubscribeTokenError, read_unsubscribe_token


class SubscribeView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "newsletter"          # 5/min/IP (DEFAULT_THROTTLE_RATES)
    serializer_class = SubscribeSerializer

    def post(self, request):
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        sub, created = NewsletterSubscriber.objects.get_or_create(
            email=data["email"], defaults={"source": data["source"]}
        )
        if not created and sub.unsubscribed_at is not None:
            # A returning subscriber — clear the opt-out, re-stamp consent.
            sub.unsubscribed_at = None
            sub.consented_at = timezone.now()
            sub.save(update_fields=["unsubscribed_at", "consented_at", "updated_at"])
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response({"detail": "Subscribed."}, status=code)


class UnsubscribeView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        token = request.query_params.get("token", "")
        try:
            email = read_unsubscribe_token(token)
        except UnsubscribeTokenError:
            return Response({"detail": "Invalid unsubscribe link."}, status=400)
        sub = NewsletterSubscriber.objects.filter(email=email).first()
        if sub and sub.unsubscribed_at is None:
            sub.unsubscribed_at = timezone.now()
            sub.save(update_fields=["unsubscribed_at", "updated_at"])
        # Idempotent: an already-unsubscribed or unknown email still returns 200 here so
        # the link never leaks whether an address is on the list.
        return Response({"detail": "You have been unsubscribed."})
