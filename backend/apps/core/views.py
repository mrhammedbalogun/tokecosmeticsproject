"""Core views. `healthz` is a liveness/readiness probe used by the proxy and CI."""
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from rest_framework import generics, permissions

from apps.core.models import Country
from apps.core.serializers import CountrySerializer


def _db_ok() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


def _redis_ok() -> bool:
    try:
        import redis

        redis.from_url(settings.REDIS_URL, socket_connect_timeout=1).ping()
        return True
    except Exception:
        return False


def healthz(request):
    db_ok = _db_ok()
    return JsonResponse(
        {
            "status": "ok" if db_ok else "degraded",
            "db": db_ok,
            "redis": _redis_ok(),
        }
    )


class CountryListView(generics.ListAPIView):
    """Public list of active markets for the storefront country switcher."""

    serializer_class = CountrySerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None  # small fixed list; return all
    queryset = (
        Country.objects.select_related("currency")
        .filter(is_active=True)
        .order_by("-is_default", "name")
    )
