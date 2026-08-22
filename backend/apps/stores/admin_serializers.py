"""Admin write shape for the store directory.

THIS FILE IS THE BOUNDARY. The admin app pre-checks a couple of things for a
friendlier inline message, exactly as the pickup-locations form does, but nothing
it does is load-bearing: every rule below is re-proved here on every request, from
ids the client sent and must not be trusted with.

The three that matter:

* **The place chain.** `state_region` must belong to `country` and `area_region`
  must be a child of `state_region`. Without this a POST naming Lagos and an LGA
  of Kano's stores a shop that the public cascade can then never surface (the
  state query finds it, the area query does not) — a row that is simultaneously
  present and invisible, which is the worst kind of wrong.
* **The finest place is mandatory.** Either an LGA (where the state has them) or a
  city (where it does not). A store filed only as "England" is not findable.
* **Phones are E.164 or rejected**, judged by `core.phones` like every other
  number in the platform, because the storefront renders `tel:` and `wa.me` links
  straight off the stored value.
"""

from rest_framework import serializers
from rest_framework.exceptions import APIException

from apps.core.models import Country, Region
from apps.core.phones import normalize_e164
from apps.stores import services
from apps.stores.models import StoreLocation


class PossibleDuplicate(APIException):
    """409, with the rows that look like the one being saved.

    Its own status code rather than a 400 so the admin UI can tell "you typed
    something invalid" (400, show field errors) from "this may already exist"
    (409, show a warning and a Save anyway button) without sniffing the body. A
    400 carrying an override affordance would be indistinguishable from a real
    validation failure to any other client, including a future script.
    """

    status_code = 409
    default_code = "possible_duplicate"


class StoreLocationAdminSerializer(serializers.ModelSerializer):
    # Keys the audit trail may keep. `notes` is included deliberately — it is
    # staff-authored operational text, not customer PII, and "who changed the note
    # about this distributor" is a question the log should answer. `confirm_duplicate`
    # is absent because it is write-only and never becomes state.
    audit_allowlist = (
        "name", "store_type", "country", "state_region", "area_region", "city_text",
        "address", "latitude", "longitude", "phone", "phone_alt", "whatsapp_phone",
        "opening_hours", "notes", "is_active",
    )

    country = serializers.PrimaryKeyRelatedField(
        # "ZZ / International" is a pricing bucket, not a place with shops in it.
        queryset=Country.objects.filter(is_rest_of_world=False),
        help_text="The market this shop is in.",
    )
    state_region = serializers.PrimaryKeyRelatedField(
        queryset=Region.objects.filter(level="state"),
    )
    area_region = serializers.PrimaryKeyRelatedField(
        queryset=Region.objects.filter(level="area"), required=False, allow_null=True,
    )
    # Write-only escape hatch for the soft duplicate warning. Not a model field:
    # "the operator looked at the warning and said yes" is a fact about one request,
    # not about the shop.
    confirm_duplicate = serializers.BooleanField(write_only=True, required=False, default=False)

    store_type_label = serializers.CharField(source="get_store_type_display", read_only=True)
    country_name = serializers.CharField(source="country.name", read_only=True)
    state_name = serializers.CharField(source="state_region.name", read_only=True)
    area_name = serializers.SerializerMethodField()
    state_label = serializers.CharField(source="country.state_label", read_only=True)
    area_label = serializers.CharField(source="country.area_label", read_only=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = StoreLocation
        fields = [
            "id", "name", "store_type", "store_type_label",
            "country", "country_name", "state_region", "state_name",
            "area_region", "area_name", "state_label", "area_label",
            "city_text", "address", "latitude", "longitude",
            "phone", "phone_alt", "whatsapp_phone", "opening_hours", "notes",
            "is_active", "status", "archived_at",
            "confirm_duplicate",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "archived_at", "status", "created_at", "updated_at"]

    def get_area_name(self, obj) -> str:
        return obj.area_region.name if obj.area_region_id else ""

    # -- field-level ---------------------------------------------------------

    def validate_name(self, value):
        value = " ".join((value or "").split())
        if not value:
            raise serializers.ValidationError("A store needs a name customers will recognise.")
        return value

    def validate_address(self, value):
        value = " ".join((value or "").split())
        if not value:
            raise serializers.ValidationError(
                "Customers need the street address to find the shop."
            )
        return value

    def _phone(self, value, *, required: bool, label: str):
        try:
            normalized = normalize_e164(value or "")
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        if required and not normalized:
            raise serializers.ValidationError(
                f"{label} is required — it is the only way a customer can call ahead."
            )
        return normalized

    def validate_phone(self, value):
        return self._phone(value, required=True, label="A phone number")

    def validate_phone_alt(self, value):
        return self._phone(value, required=False, label="The second phone number")

    def validate_whatsapp_phone(self, value):
        return self._phone(value, required=False, label="The WhatsApp number")

    # -- object-level --------------------------------------------------------

    def validate(self, attrs):
        """The place chain, the finest-place rule, then the duplicate warning.

        Reads through to `self.instance` for every field a PATCH might not carry —
        a PATCH that changes only the phone must still be judged against the state
        and area already stored, or a partial update becomes a hole in all three
        rules above.
        """
        def current(field):
            if field in attrs:
                return attrs[field]
            return getattr(self.instance, field, None) if self.instance else None

        country = current("country")
        state = current("state_region")
        area = current("area_region")

        if country is None or state is None:
            raise serializers.ValidationError({
                "state_region": "Pick the country and state this shop is in.",
            })
        if state.country_code != country.code:
            raise serializers.ValidationError({
                "state_region": f"{state.name} is not in {country.name}.",
            })
        if area is not None and area.parent_id != state.pk:
            raise serializers.ValidationError({
                "area_region": f"{area.name} is not in {state.name}.",
            })

        # The finest place available for this state has to be filled in, or the
        # shop is filed somewhere nobody can search. Which one that is depends on
        # the country: NG states have LGAs, GB/US/CA level-1 regions have none, so
        # asking for an LGA there would be unanswerable and asking for nothing
        # would file every English store under "England".
        state_has_areas = Region.objects.filter(parent=state, level="area").exists()
        if state_has_areas and area is None:
            label = (country.area_label or "area").lower()
            raise serializers.ValidationError({
                "area_region": f"Pick the {label} — customers search by it.",
            })
        if not state_has_areas and not (current("city_text") or "").strip():
            raise serializers.ValidationError({
                "city_text": f"{state.name} has no districts on file, so the town or "
                             f"city is what a customer will look for.",
            })
        if not state_has_areas and area is not None:
            raise serializers.ValidationError({
                "area_region": f"{state.name} has no districts on file.",
            })

        self._check_pin(attrs, current=current)
        self._warn_about_duplicates(attrs, country=country, state=state, area=area,
                                    current=current)
        return attrs

    def _check_pin(self, attrs, *, current):
        """A pin is both coordinates or neither, and each inside its range.

        `maps_url` only uses the pin when BOTH are set, so a row saved with a latitude
        and no longitude looks pinned in the admin and is not — "Get directions" quietly
        searches the address text instead, and nobody finds out until a customer lands
        on the wrong street. Refusing the half-pin is the only honest answer.

        Range-checked here rather than by the column: `DecimalField(max_digits=9)`
        happily stores 999.000000, and a latitude of 999 is not a place.
        """
        if not ({"latitude", "longitude"} & set(attrs)):
            return
        lat, lng = current("latitude"), current("longitude")
        if (lat is None) != (lng is None):
            missing = "longitude" if lng is None else "latitude"
            raise serializers.ValidationError({
                missing: "A pin needs both coordinates — add this one or clear the other.",
            })
        if lat is not None and not -90 <= lat <= 90:
            raise serializers.ValidationError({"latitude": "Latitude runs from -90 to 90."})
        if lng is not None and not -180 <= lng <= 180:
            raise serializers.ValidationError({"longitude": "Longitude runs from -180 to 180."})

    def _warn_about_duplicates(self, attrs, *, country, state, area, current):
        """Raise 409 once, unless the operator already said "save anyway".

        Only for requests that actually touch an identifying field. Flipping
        `is_active` on a row that has always had a look-alike next door must not
        pop a warning about a decision nobody is making.
        """
        if attrs.get("confirm_duplicate"):
            return
        identifying = {"name", "address", "phone", "phone_alt", "whatsapp_phone",
                       "country", "state_region", "area_region"}
        if self.instance is not None and not (identifying & set(attrs)):
            return

        hints = services.possible_duplicates(
            country=country,
            state=state,
            area=area,
            name=current("name") or "",
            address=current("address") or "",
            phones=[current("phone") or "", current("phone_alt") or ""],
            exclude_pk=self.instance.pk if self.instance else None,
        )
        if not hints:
            return
        raise PossibleDuplicate({
            "detail": "This looks like a shop that is already on file.",
            "possible_duplicates": [
                {"kind": h.kind, "reason": h.reason, "label": h.label, "detail": h.detail,
                 "id": h.id}
                for h in hints
            ],
        })

    def create(self, validated_data):
        validated_data.pop("confirm_duplicate", None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("confirm_duplicate", None)
        return super().update(instance, validated_data)
