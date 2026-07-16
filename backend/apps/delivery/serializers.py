from rest_framework import serializers

from apps.core.models import Region


class RegionSerializer(serializers.ModelSerializer):
    has_children = serializers.SerializerMethodField()

    class Meta:
        model = Region
        fields = ["id", "name", "level", "has_children"]

    def get_has_children(self, obj) -> bool:
        return obj.children.exists()
