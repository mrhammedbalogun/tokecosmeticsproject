"""What a customer is allowed to see about a store, and in what shape.

READ-ONLY AND ALLOWLISTED. Every field below is named explicitly rather than
inherited from `fields = "__all__"`: this serialiser sits on an unauthenticated
endpoint, and the model carries a staff-only `notes` column plus the two derived
match keys. A future column must be added here deliberately to become public.

Formatting happens HERE and not in the browser (the brief's "display data
professionally"): the phone is rendered once, the maps link is composed once, and
the storefront cannot drift from the admin about how either looks.
"""

from rest_framework import serializers

from apps.core.phones import format_display
from apps.stores.models import StoreLocation
from apps.stores.services import maps_url, whatsapp_url


class PlaceSerializer(serializers.Serializer):
    """One option in the country / state / area cascade (`services.Place`)."""

    slug = serializers.CharField()
    name = serializers.CharField()
    store_count = serializers.IntegerField()
    has_children = serializers.BooleanField()
    # Countries only.
    code = serializers.CharField(allow_null=True, required=False)
    state_label = serializers.CharField(allow_null=True, required=False)
    area_label = serializers.CharField(allow_null=True, required=False)


class StoreSerializer(serializers.ModelSerializer):
    """A public store card.

    `id` is present and is a React key, nothing else — it is never rendered, and
    the URL vocabulary for this feature is slugs precisely so a customer never sees
    a primary key. It is here rather than a synthesised public reference because
    inventing a second identifier for a directory of publicly-advertised shop
    addresses would be ceremony: there is nothing to enumerate that the page does
    not already show.
    """

    store_type_label = serializers.CharField(source="get_store_type_display", read_only=True)
    country = serializers.CharField(source="country.name", read_only=True)
    country_code = serializers.CharField(source="country.code", read_only=True)
    state = serializers.CharField(source="state_region.name", read_only=True)
    area = serializers.SerializerMethodField()
    city = serializers.CharField(source="city_text", read_only=True)
    phone_display = serializers.SerializerMethodField()
    phone_alt_display = serializers.SerializerMethodField()
    whatsapp_url = serializers.SerializerMethodField()
    directions_url = serializers.SerializerMethodField()

    class Meta:
        model = StoreLocation
        fields = [
            "id",
            "name",
            "store_type",
            "store_type_label",
            "address",
            "city",
            "area",
            "state",
            "country",
            "country_code",
            # E.164, for `tel:` — the DIALLABLE form. `phone_display` beside it is
            # the readable one; a card shows the second and links the first.
            "phone",
            "phone_display",
            "phone_alt",
            "phone_alt_display",
            "whatsapp_url",
            "opening_hours",
            "directions_url",
        ]
        read_only_fields = fields

    def _viewer_country(self) -> str:
        """The market the request is in, so a Nigerian reader gets "0802 390 0964"
        and a reader abroad gets "+234 802 390 0964". Falls back to the STORE's own
        country, which makes the national form the default in a shell with no
        request (schema generation, tests)."""
        request = self.context.get("request")
        if request is not None:
            header = request.headers.get("X-Country", "")
            if header:
                return header
        return self.context.get("viewer_country", "")

    def get_area(self, obj) -> str:
        return obj.area_region.name if obj.area_region_id else ""

    def get_phone_display(self, obj) -> str:
        return format_display(obj.phone, self._viewer_country())

    def get_phone_alt_display(self, obj) -> str:
        return format_display(obj.phone_alt, self._viewer_country())

    def get_whatsapp_url(self, obj) -> str:
        return whatsapp_url(obj.whatsapp_phone)

    def get_directions_url(self, obj) -> str:
        return maps_url(obj)
