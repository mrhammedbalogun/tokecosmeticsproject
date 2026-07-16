from django.urls import path

from apps.checkout.views import PaymentMethodsView

urlpatterns = [
    path("checkout/payment-methods/", PaymentMethodsView.as_view(), name="checkout-payment-methods"),
]
