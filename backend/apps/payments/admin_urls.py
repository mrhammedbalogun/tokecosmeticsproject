from django.urls import path

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
