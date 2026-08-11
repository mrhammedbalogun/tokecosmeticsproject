from rest_framework import serializers

from apps.core.models import Region


class RegionSerializer(serializers.ModelSerializer):
    has_children = serializers.SerializerMethodField()

    class Meta:
        model = Region
        # Centroids ride along for the storefront's confirm-your-pin map prefill
        # (Plan-32b slice 3): the map centres on the chosen LGA before any Places
        # pick exists. Null for regions never seeded — the map then falls back.
        fields = ["id", "name", "level", "has_children", "latitude", "longitude"]

    def get_has_children(self, obj) -> bool:
        return obj.children.exists()
