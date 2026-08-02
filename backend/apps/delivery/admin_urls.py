from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.delivery.admin_views import (
    AdminGigCaptureView,
    AdminGigLabelView,
    AdminGigShipmentView,
    DeliveryOptionAdminViewSet,
    RegionAdminViewSet,
)

router = SimpleRouter()
router.register("delivery-options", DeliveryOptionAdminViewSet, basename="admin-delivery-option")
router.register("regions", RegionAdminViewSet, basename="admin-region")

urlpatterns = router.urls + [
    # Mounted here (delivery owns GIG) but addressed by order number, beside the other
    # order endpoints the fulfilment screen already talks to.
    path("orders/<str:number>/gig/", AdminGigShipmentView.as_view(), name="admin-gig-shipment"),
    path("orders/<str:number>/gig/capture/", AdminGigCaptureView.as_view(),
         name="admin-gig-capture"),
    path("orders/<str:number>/gig/label/", AdminGigLabelView.as_view(), name="admin-gig-label"),
]
