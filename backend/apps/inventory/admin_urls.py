"""Inventory admin routes. SimpleRouter for the reason given in
apps/catalog/admin_urls.py: DefaultRouter's api-root would be an ungated route on the
admin prefix."""
from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.inventory.admin_views import (
    StockCSVExportView,
    StockCSVImportView,
    StockItemAdminViewSet,
    StockMovementListView,
)

router = SimpleRouter()
router.register("stock", StockItemAdminViewSet, basename="admin-stock")

# Plain paths BEFORE the router so `stock/export.csv` / `stock/movements/` aren't
# captured as a stock pk detail route.
urlpatterns = [
    path("stock/export.csv", StockCSVExportView.as_view(), name="admin-stock-export"),
    path("stock/import.csv", StockCSVImportView.as_view(), name="admin-stock-import"),
    path("stock/movements/", StockMovementListView.as_view(), name="admin-stock-movements"),
] + router.urls
