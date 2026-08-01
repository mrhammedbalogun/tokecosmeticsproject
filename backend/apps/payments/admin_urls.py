from django.urls import path

from rest_framework.routers import SimpleRouter

from apps.payments.admin_config_views import (
    BankAccountAdminViewSet,
    CountryPaymentGatewayAdminViewSet,
)
from apps.payments.views import ConfirmManualReceiptView, ManualRefundView, OrderRefundView

urlpatterns = [
    # POST /api/v1/admin/orders/{number}/refunds/
    path("orders/<str:number>/refunds/", OrderRefundView.as_view(), name="admin-order-refunds"),
    # POST /api/v1/admin/orders/{number}/manual-refund/
    path("orders/<str:number>/manual-refund/", ManualRefundView.as_view(),
         name="admin-manual-refund"),
    # POST /api/v1/admin/orders/{number}/confirm-payment/
    path("orders/<str:number>/confirm-payment/", ConfirmManualReceiptView.as_view(),
         name="admin-confirm-manual-receipt"),
]

# Money config (Plan-19b). A router rather than hand-written paths: these are ordinary
# CRUD resources, unlike the action-shaped routes above.
_router = SimpleRouter()
_router.register("bank-accounts", BankAccountAdminViewSet, basename="admin-bank-account")
_router.register(
    "payment-gateways", CountryPaymentGatewayAdminViewSet, basename="admin-payment-gateway"
)
urlpatterns += _router.urls
