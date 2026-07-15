from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.inventory.admin_views import (
    StockCSVExportView,
    StockCSVImportView,
    StockItemAdminViewSet,
    StockMovementListView,
)

router = DefaultRouter()
router.register("stock", StockItemAdminViewSet, basename="admin-stock")

# Plain paths BEFORE the router so `stock/export.csv` / `stock/movements/` aren't
# captured as a stock pk detail route.
urlpatterns = [
    path("stock/export.csv", StockCSVExportView.as_view(), name="admin-stock-export"),
    path("stock/import.csv", StockCSVImportView.as_view(), name="admin-stock-import"),
    path("stock/movements/", StockMovementListView.as_view(), name="admin-stock-movements"),
] + router.urls
