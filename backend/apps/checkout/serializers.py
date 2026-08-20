from rest_framework import serializers

from apps.accounts.serializers import AddressSerializer
from apps.core.phones import normalize_e164


class QuoteRequestSerializer(serializers.Serializer):
    # UUIDField (not CharField) so a malformed id fails validation here with a clean
    # 400, rather than reaching get_object_or_404's UUIDField lookup and raising an
    # uncaught ValidationError -> 500. Mirrors apps/carts/services.py's _safe_uuid,
    # which treats a bad cart id as "not found" for the same reason.
    cart_id = serializers.UUIDField()
    coupon_code = serializers.CharField(required=False, allow_blank=True, default="")
    address_id = serializers.IntegerField(required=False)
    # CharField, not IntegerField, since Plan-39: the option id space is mixed —
    # DeliveryOption pks stay integers, partner zones ride as "pz:{pk}". CharField
    # str()-coerces an integer from an older client, and the views compare via
    # services.option_id_matches, which str()s both sides.
    delivery_option_id = serializers.CharField(required=False)
    # The chosen pickup centre (32b slice 4) — keeps the preview priced to the same
    # centre place_order will re-quote, so expected_total can't mismatch on pickup.
    gig_centre_id = serializers.IntegerField(required=False)


# --- guest checkout (Plan-38) -------------------------------------------------
#
# Guests have no Address rows: the inline address validates through the SAME
# serializer the saved-address flow uses (per-country required fields, region
# integrity, the create-only LGA rule — instance is None here, so it applies) and is
# then materialised as an UNSAVED Address instance via build_unsaved_address. The
# quoting engine and the order snapshot only ever read fields and forward FKs off it,
# so nothing needs a pk and nothing is written to the address table.


def build_unsaved_address(validated: dict):
    """An unsaved Address from GuestAddressSerializer.validated_data. The user FK is
    deliberately left unset — this object exists to be quoted against and snapshotted
    into the order JSON, never saved."""
    from apps.accounts.models import Address

    return Address(**validated)


class GuestAddressSerializer(AddressSerializer):
    """AddressSerializer, minus any temptation to save. create/update are stubbed
    loudly so a future caller cannot quietly start writing user-less address rows."""

    def create(self, validated_data):  # pragma: no cover - guard, not a path
        raise NotImplementedError("Guest addresses are never saved.")

    def update(self, instance, validated_data):  # pragma: no cover - guard, not a path
        raise NotImplementedError("Guest addresses are never saved.")


class GuestContactMixin(serializers.Serializer):
    """The two facts a guest must hand over (Plan-38 product ruling): email + phone.
    Phone goes through the same E.164 gate as registration — it is the number GIG
    actually dials."""

    guest_email = serializers.EmailField()
    guest_phone = serializers.CharField(max_length=32)

    def validate_guest_email(self, value):
        return value.lower()

    def validate_guest_phone(self, value):
        try:
            return normalize_e164(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))


class GuestCheckoutSerializer(GuestContactMixin, serializers.Serializer):
    """The guest half of POST /checkout/: contact + inline address. The rest of the
    payload (cart_id, delivery_option_id, gateway, coupon…) is read by the view
    exactly as on the authed path, so the two paths cannot drift."""

    address = GuestAddressSerializer()


class GuestDeliveryOptionsSerializer(serializers.Serializer):
    """POST /checkout/guest/delivery-options/ — POST, not GET: the inline address is
    PII and must stay out of access logs. cart_id is required as a plausibility gate
    (a non-empty guest cart) so the live GIG quote engine is not free to enumerate."""

    cart_id = serializers.UUIDField()
    address = GuestAddressSerializer()


class GuestGigCentresSerializer(serializers.Serializer):
    """POST /checkout/guest/gig-centres/ — same shape and same gate as above."""

    cart_id = serializers.UUIDField()
    address = GuestAddressSerializer()


class GuestQuoteRequestSerializer(serializers.Serializer):
    """POST /checkout/guest/quote/ — QuoteRequestSerializer's guest twin: the address
    arrives inline instead of by id, and guest_email rides along so the coupon
    preview enforces the same per-email limits place_order will (a preview that says
    "valid" for a code the real checkout refuses is worse than no preview)."""

    cart_id = serializers.UUIDField()
    coupon_code = serializers.CharField(required=False, allow_blank=True, default="")
    guest_email = serializers.EmailField(required=False, allow_blank=True, default="")
    address = GuestAddressSerializer(required=False)
    # CharField for the same mixed-id-space reason as QuoteRequestSerializer above.
    delivery_option_id = serializers.CharField(required=False)
    gig_centre_id = serializers.IntegerField(required=False)
