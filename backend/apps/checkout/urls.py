from django.urls import path

from apps.checkout.views import (
    BuyNowView,
    CheckoutView,
    DeliveryOptionsView,
    GigCentresView,
    GuestDeliveryOptionsView,
    GuestGigCentresView,
    GuestQuoteView,
    OrderPayView,
    PaymentMethodsView,
    QuoteView,
)

urlpatterns = [
    path("orders/<str:number>/pay/", OrderPayView.as_view(), name="order-pay"),
    path("checkout/quote/", QuoteView.as_view(), name="checkout-quote"),
    # Guest twins (Plan-38): POST-only, inline address, non-empty guest cart required.
    path("checkout/guest/quote/", GuestQuoteView.as_view(), name="checkout-guest-quote"),
    path("checkout/guest/delivery-options/", GuestDeliveryOptionsView.as_view(),
         name="checkout-guest-delivery-options"),
    path("checkout/guest/gig-centres/", GuestGigCentresView.as_view(),
         name="checkout-guest-gig-centres"),
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("checkout/payment-methods/", PaymentMethodsView.as_view(), name="checkout-payment-methods"),
    path("checkout/delivery-options/", DeliveryOptionsView.as_view(), name="checkout-delivery-options"),
    path("checkout/gig-centres/", GigCentresView.as_view(), name="checkout-gig-centres"),
    path("checkout/buy-now/", BuyNowView.as_view(), name="checkout-buy-now"),
]
