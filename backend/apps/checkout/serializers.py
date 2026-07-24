from rest_framework import serializers


class QuoteRequestSerializer(serializers.Serializer):
    # UUIDField (not CharField) so a malformed id fails validation here with a clean
    # 400, rather than reaching get_object_or_404's UUIDField lookup and raising an
    # uncaught ValidationError -> 500. Mirrors apps/carts/services.py's _safe_uuid,
    # which treats a bad cart id as "not found" for the same reason.
    cart_id = serializers.UUIDField()
    coupon_code = serializers.CharField(required=False, allow_blank=True, default="")
    address_id = serializers.IntegerField(required=False)
    delivery_option_id = serializers.IntegerField(required=False)
