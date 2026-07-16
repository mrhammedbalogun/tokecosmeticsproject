from django.urls import path

from apps.payments.views import PaymentStatusView
from apps.payments.views_webhooks import GatewayWebhookView

urlpatterns = [
    # POST /api/v1/webhooks/paystack/  (flutterwave|stripe|paypal|…)
    path("webhooks/<str:gateway>/", GatewayWebhookView.as_view(), name="gateway-webhook"),
    # POST /api/v1/payments/{reference}/verify/ — customer return-from-redirect check
    path("payments/<str:reference>/verify/", PaymentStatusView.as_view(), name="payment-status"),
]
