from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.delivery.admin_views import (
    AdminGigCaptureView,
    AdminGigLabelView,
    AdminGigShipmentListView,
    AdminGigShipmentView,
    DeliveryOptionAdminViewSet,
    DeliveryPartnerAdminViewSet,
    PartnerZoneAdminViewSet,
    SenderLocationAdminViewSet,
    RegionAdminViewSet,
)

router = SimpleRouter()
router.register("delivery-options", DeliveryOptionAdminViewSet, basename="admin-delivery-option")
router.register("regions", RegionAdminViewSet, basename="admin-region")
router.register("sender-locations", SenderLocationAdminViewSet,
                basename="admin-sender-location")
# Plan-39: partner accounts (Owner) + their rate-card rows (Manager and above).
router.register("partners", DeliveryPartnerAdminViewSet, basename="admin-partner")
router.register("partner-zones", PartnerZoneAdminViewSet, basename="admin-partner-zone")

urlpatterns = router.urls + [
    # The deliveries table (Plan-35): every shipment, filterable by origin — the
    # packing-desk view. Read-only; capture lives on the order page.
    path("gig-shipments/", AdminGigShipmentListView.as_view(), name="admin-gig-shipments"),
    # Mounted here (delivery owns GIG) but addressed by order number, beside the other
    # order endpoints the fulfilment screen already talks to.
    path("orders/<str:number>/gig/", AdminGigShipmentView.as_view(), name="admin-gig-shipment"),
    path("orders/<str:number>/gig/capture/", AdminGigCaptureView.as_view(),
         name="admin-gig-capture"),
    path("orders/<str:number>/gig/label/", AdminGigLabelView.as_view(), name="admin-gig-label"),
]
