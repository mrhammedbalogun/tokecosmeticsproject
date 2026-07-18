from django.urls import path

from apps.shipping.views import (
    CancelQuoteView,
    FreightReceiptView,
    QuoteFreightView,
    WaiveFreightView,
)

urlpatterns = [
    # POST /api/v1/admin/orders/{number}/freight/quote/
    path("orders/<str:number>/freight/quote/", QuoteFreightView.as_view(),
         name="admin-freight-quote"),
    # POST /api/v1/admin/orders/{number}/freight/waive/
    path("orders/<str:number>/freight/waive/", WaiveFreightView.as_view(),
         name="admin-freight-waive"),
    # POST /api/v1/admin/orders/{number}/freight/cancel/
    path("orders/<str:number>/freight/cancel/", CancelQuoteView.as_view(),
         name="admin-freight-cancel"),
    # POST /api/v1/admin/orders/{number}/freight/receipt/
    path("orders/<str:number>/freight/receipt/", FreightReceiptView.as_view(),
         name="admin-freight-receipt"),
]
