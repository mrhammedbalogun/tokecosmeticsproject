from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView

from apps.core.models import Region
from apps.delivery.serializers import RegionSerializer


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
