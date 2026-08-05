from rest_framework import serializers

from apps.core.models import AuditLog, Country, Currency


class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ["code", "symbol", "decimal_places"]


class CountrySerializer(serializers.ModelSerializer):
    currency = CurrencySerializer(read_only=True)

    class Meta:
        model = Country
        fields = [
            "code",
            "name",
            "currency",
            "is_default",
            "is_rest_of_world",
            "tax_rate_percent",
            "prices_include_tax",
            "state_label",
            "area_label",
        ]


class AuditLogSerializer(serializers.ModelSerializer):
    """Read shape for the audit log. EVERY field is read-only, twice over.

    `read_only_fields = fields` is belt; the endpoint being a `ListAPIView` with no
    create route is braces; `AuditLog.save()` refusing to rewrite a row is the actual
    guarantee. Three fences for one property is not excessive here — the property is
    that this table cannot be edited through the API, and it is the whole reason the
    table is worth reading.

    `actor_email` is exposed rather than the FK's current address on purpose: it is the
    SNAPSHOT taken when the action happened, so a row still names who did it after that
    account is deleted (`actor` goes NULL) or after they change their address.
    """

    class Meta:
        model = AuditLog
        fields = [
            "id", "created_at", "actor", "actor_email", "token_jti", "client_ip",
            "model_label", "object_id", "action", "changes",
        ]
        read_only_fields = fields
