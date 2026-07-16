from django.urls import path

from apps.payments.views_webhooks import GatewayWebhookView

urlpatterns = [
    # POST /api/v1/webhooks/paystack/  (flutterwave|stripe|paypal|…)
    path("webhooks/<str:gateway>/", GatewayWebhookView.as_view(), name="gateway-webhook"),
]
