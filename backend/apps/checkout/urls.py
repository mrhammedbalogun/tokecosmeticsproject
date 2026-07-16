from django.urls import path

from apps.checkout.views import DeliveryOptionsView, PaymentMethodsView

urlpatterns = [
    path("checkout/payment-methods/", PaymentMethodsView.as_view(), name="checkout-payment-methods"),
    path("checkout/delivery-options/", DeliveryOptionsView.as_view(), name="checkout-delivery-options"),
]
