from rest_framework import serializers


class SubscribeSerializer(serializers.Serializer):
    email = serializers.EmailField()
    source = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")

    def validate_email(self, value):
        return value.lower()
