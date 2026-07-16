from django.urls import path

from apps.orders.views import (
    AdminOrderDetailView,
    AdminOrderListView,
    AdminOrderNoteView,
    AdminOrderTrackingView,
    AdminOrderTransitionView,
    AdminResolveReviewView,
)

urlpatterns = [
    path("orders/", AdminOrderListView.as_view(), name="admin-order-list"),
    path("orders/<str:number>/", AdminOrderDetailView.as_view(), name="admin-order-detail"),
    path("orders/<str:number>/transition/", AdminOrderTransitionView.as_view(),
         name="admin-order-transition"),
    path("orders/<str:number>/tracking/", AdminOrderTrackingView.as_view(),
         name="admin-order-tracking"),
    path("orders/<str:number>/note/", AdminOrderNoteView.as_view(), name="admin-order-note"),
    path("orders/<str:number>/resolve-review/", AdminResolveReviewView.as_view(),
         name="admin-order-resolve-review"),
]
