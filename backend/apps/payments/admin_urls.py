from django.urls import path

from apps.payments.views import OrderRefundView

urlpatterns = [
    # POST /api/v1/admin/orders/{number}/refunds/
    path("orders/<str:number>/refunds/", OrderRefundView.as_view(), name="admin-order-refunds"),
]
