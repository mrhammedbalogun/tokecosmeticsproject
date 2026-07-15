from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.catalog.api_serializers import ProductListSerializer
from apps.search.backends import get_backend


class SearchView(generics.ListAPIView):
    serializer_class = ProductListSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "search"

    def get_queryset(self):
        return get_backend().search_queryset(self.request.query_params, self.request.country)


class SuggestView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "suggest"

    def get(self, request):
        results = get_backend().suggest(request.query_params.get("q", ""), request.country)
        return Response(results)
