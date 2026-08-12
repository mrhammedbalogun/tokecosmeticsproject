"""Money configuration: bank accounts and per-country gateways (Plan-19b).

`settings.manage`, which is Owner-only. `rbac.py` already reasoned this out before either
screen existed: "settings covers the payout bank account, which is the single
highest-value target in the system". A Manager runs the shop; only the Owner changes where
money lands.
"""
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.core.audit import AdminAuditMixin
from apps.payments.admin_config_serializers import (
    BankAccountAdminSerializer,
    CountryPaymentGatewayAdminSerializer,
)
from apps.payments.models import BankAccount, CountryPaymentGateway


class BankAccountAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """CRUD minus delete. Deleting the row a country pays into does not disable bank
    transfer — it makes `initiate()` fail for every customer in that market with nothing
    to read. `is_active=False` is the switch that means "stop offering this", and it keeps
    the history of what the number used to be.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("settings.manage")]
    serializer_class = BankAccountAdminSerializer
    audit_serializers = (BankAccountAdminSerializer,)
    queryset = BankAccount.objects.select_related("country", "currency").all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["country", "is_active"]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]


class CountryPaymentGatewayAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """The per-market gateway list. DELETE is allowed here, unlike the bank account:
    removing a row means "this market never offered this gateway", which is a coherent
    thing to say and destroys no history that matters — `Payment.gateway` is a plain
    CharField, so past orders keep their gateway name either way.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("settings.manage")]
    serializer_class = CountryPaymentGatewayAdminSerializer
    audit_serializers = (CountryPaymentGatewayAdminSerializer,)
    queryset = CountryPaymentGateway.objects.select_related(
        "country", "country__currency"
    ).all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["country", "gateway", "is_active"]

    @action(detail=False, methods=["get"])
    def catalog(self, request):
        """`GET /admin/payment-gateways/catalog/` — every gateway adapter the platform
        HAS, whether or not any market offers it. This is the "add a method to a market"
        menu: the model's `gateway` field is deliberately free text, so without this the
        UI would have to hardcode the adapter list and drift from the registry.

        `missing_settings` is key-level truth only; bank_transfer's configuredness is
        per-country (it needs an account, not keys), which the row serializer answers.
        """
        from apps.payments.checks import missing_settings_for
        from apps.payments.gateways.registry import _REGISTRY

        return Response([
            {
                "code": code,
                # [] = no restriction (bank_transfer declares none — wires work in any
                # currency); the row serializer uses the same convention.
                "supported_currencies": sorted(
                    getattr(gateway, "supported_currencies", [])
                ),
                "missing_settings": missing_settings_for(code),
                "needs": "bank_account" if code == "bank_transfer" else "api_keys",
            }
            for code, gateway in sorted(_REGISTRY.items())
        ])
