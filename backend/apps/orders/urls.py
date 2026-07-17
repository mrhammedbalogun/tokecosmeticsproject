from django.urls import path

from apps.orders.views import OrderDetailView, OrderInvoiceView, OrderListView

urlpatterns = [
    path("orders/", OrderListView.as_view(), name="order-list"),
    # invoice.pdf before the detail route — otherwise <str:number> swallows it.
    path("orders/<str:number>/invoice.pdf", OrderInvoiceView.as_view(), name="order-invoice"),
    path("orders/<str:number>/", OrderDetailView.as_view(), name="order-detail"),
]
