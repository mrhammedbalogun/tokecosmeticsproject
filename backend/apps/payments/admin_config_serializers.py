"""Serializers for the money-config surfaces (Plan-19b).

Both models here were reachable only through `/django-admin/`, which is **denied outright
at the Apache vhost** (`config/urls.py:3-9`). So "Django admin covers launch", the reason
Plan-09b gave for deferring the bank-account screen, described a control that does not
exist — and changing the account number customers wire money to meant a raw SQL UPDATE.
"""
from rest_framework import serializers

from apps.payments.models import BankAccount, CountryPaymentGateway


class BankAccountAdminSerializer(serializers.ModelSerializer):
    """THE most consequential row in the system: `BankAccount`'s own docstring says "this
    row IS the payment page for that country", and Plan-16 Amendment 1 names the payout
    account as the highest-value target here. Hence `settings.manage` (Owner only) on the
    view, and hence every field on the audit allow-list — a changed account number must be
    answerable with "who, when, from what to what".
    """

    audit_allowlist = (
        "country", "currency", "bank_name", "account_name", "account_number",
        "extra", "instructions", "is_active",
    )

    country_name = serializers.CharField(source="country.name", read_only=True)

    class Meta:
        model = BankAccount
        fields = [
            "id", "country", "country_name", "currency", "bank_name", "account_name",
            "account_number", "extra", "instructions", "is_active", "updated_at",
        ]


class CountryPaymentGatewayAdminSerializer(serializers.ModelSerializer):
    """Which gateways a market offers. Turning one on is what makes cards live, and it is
    the switch Plan-09 left to a production DB edit.

    The read-only trio (`configured`, `missing_settings`, `supported_currencies`) mirrors
    the registry's request-time filter: `is_active` is merchandising INTENT, and the
    storefront menu intersects it with configuredness. Without these fields the admin
    toggle lies — a row can say "on" while `active_gateways_for` silently drops it. The
    UI's job is to show that divergence, not to prevent it (enabling a gateway before its
    keys are deployed is a legitimate sequencing choice)."""

    audit_allowlist = ("country", "gateway", "is_active", "sort_order")

    country_name = serializers.CharField(source="country.name", read_only=True)
    country_currency = serializers.CharField(source="country.currency_id", read_only=True)
    configured = serializers.SerializerMethodField()
    missing_settings = serializers.SerializerMethodField()
    supported_currencies = serializers.SerializerMethodField()

    class Meta:
        model = CountryPaymentGateway
        fields = [
            "id", "country", "country_name", "country_currency", "gateway",
            "is_active", "sort_order", "configured", "missing_settings",
            "supported_currencies",
        ]

    def get_configured(self, obj) -> bool:
        from apps.payments.gateways.registry import _is_configured

        return _is_configured(obj.gateway, obj.country)

    def get_missing_settings(self, obj) -> list[str]:
        from apps.payments.checks import missing_settings_for

        return missing_settings_for(obj.gateway)

    def get_supported_currencies(self, obj) -> list[str]:
        # [] means "no restriction": bank_transfer declares no supported_currencies (a
        # wire works in any currency). `gateway` is also a free CharField, so a row can
        # name an adapter that no longer exists — that answers [] too rather than 500
        # (the row stays visible and deletable, and can't be charged through anyway).
        from apps.payments.gateways.registry import UnknownGateway, get_gateway

        try:
            return sorted(getattr(get_gateway(obj.gateway), "supported_currencies", []))
        except UnknownGateway:
            return []
