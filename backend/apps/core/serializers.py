from rest_framework import serializers

from apps.core.models import Country, Currency


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
        ]
