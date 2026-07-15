from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.inventory.admin_views import StockItemAdminViewSet, StockMovementListView

router = DefaultRouter()
router.register("stock", StockItemAdminViewSet, basename="admin-stock")

# Plain path BEFORE the router so `stock/movements/` isn't captured as a stock pk.
urlpatterns = [
    path("stock/movements/", StockMovementListView.as_view(), name="admin-stock-movements"),
] + router.urls
