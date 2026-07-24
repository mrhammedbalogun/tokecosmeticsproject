from django.urls import path

from apps.checkout.views import (
    BuyNowView,
    CheckoutView,
    DeliveryOptionsView,
    PaymentMethodsView,
    QuoteView,
)

urlpatterns = [
    path("checkout/quote/", QuoteView.as_view(), name="checkout-quote"),
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("checkout/payment-methods/", PaymentMethodsView.as_view(), name="checkout-payment-methods"),
    path("checkout/delivery-options/", DeliveryOptionsView.as_view(), name="checkout-delivery-options"),
    path("checkout/buy-now/", BuyNowView.as_view(), name="checkout-buy-now"),
]
