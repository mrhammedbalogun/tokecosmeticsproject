from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.delivery.admin_views import (
    AdminAajCaptureView,
    AdminAajCheckView,
    AdminAajLabelView,
    AdminAajShipmentListView,
    AdminAajShipmentView,
    AdminAajVoidView,
    AdminGigCaptureView,
    AdminGigLabelView,
    AdminGigShipmentListView,
    AdminGigShipmentView,
    AdminPartnerShipmentListView,
    DeliveryBlockAdminViewSet,
    DeliveryFeeMaskAdminViewSet,
    DeliveryOptionAdminViewSet,
    DeliveryPartnerAdminViewSet,
    DeliveryServiceListView,
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
# Plan-41: per-place service blocks + per-service fee masks (Manager and above).
router.register("delivery-blocks", DeliveryBlockAdminViewSet, basename="admin-delivery-block")
router.register("delivery-fee-masks", DeliveryFeeMaskAdminViewSet,
                basename="admin-delivery-fee-mask")

urlpatterns = router.urls + [
    # Plan-41: the service picker behind the block/mask forms.
    path("delivery-services/", DeliveryServiceListView.as_view(),
         name="admin-delivery-services"),
    # The deliveries table (Plan-35): every shipment, filterable by origin — the
    # packing-desk view. Read-only; capture lives on the order page.
    path("gig-shipments/", AdminGigShipmentListView.as_view(), name="admin-gig-shipments"),
    # The partner deliveries table — the GIG table's sibling for couriers with no
    # API (BrandnPack). Read-only; status moves live on the order page.
    path("partner-shipments/", AdminPartnerShipmentListView.as_view(),
         name="admin-partner-shipments"),
    # Mounted here (delivery owns GIG) but addressed by order number, beside the other
    # order endpoints the fulfilment screen already talks to.
    path("orders/<str:number>/gig/", AdminGigShipmentView.as_view(), name="admin-gig-shipment"),
    path("orders/<str:number>/gig/capture/", AdminGigCaptureView.as_view(),
         name="admin-gig-capture"),
    path("orders/<str:number>/gig/label/", AdminGigLabelView.as_view(), name="admin-gig-label"),
    # AAJ Express (Plan-43): the GIG surface's sibling, plus check (reconcile) and void.
    path("aaj-shipments/", AdminAajShipmentListView.as_view(), name="admin-aaj-shipments"),
    path("orders/<str:number>/aaj/", AdminAajShipmentView.as_view(), name="admin-aaj-shipment"),
    path("orders/<str:number>/aaj/capture/", AdminAajCaptureView.as_view(),
         name="admin-aaj-capture"),
    path("orders/<str:number>/aaj/check/", AdminAajCheckView.as_view(), name="admin-aaj-check"),
    path("orders/<str:number>/aaj/void/", AdminAajVoidView.as_view(), name="admin-aaj-void"),
    path("orders/<str:number>/aaj/label/", AdminAajLabelView.as_view(), name="admin-aaj-label"),
]
