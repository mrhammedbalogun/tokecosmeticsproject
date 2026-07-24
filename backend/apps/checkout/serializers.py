from rest_framework import serializers


class QuoteRequestSerializer(serializers.Serializer):
    cart_id = serializers.CharField()
    coupon_code = serializers.CharField(required=False, allow_blank=True, default="")
    address_id = serializers.IntegerField(required=False)
    delivery_option_id = serializers.IntegerField(required=False)
