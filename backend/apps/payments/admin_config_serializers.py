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
    the switch Plan-09 left to a production DB edit."""

    audit_allowlist = ("country", "gateway", "is_active", "sort_order")

    class Meta:
        model = CountryPaymentGateway
        fields = "__all__"
