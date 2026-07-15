from django.urls import path

from apps.catalog.api_views import (
    BrandListView,
    CategoryTreeView,
    CollectionDetailView,
    ProductDetailView,
    ProductListView,
)

urlpatterns = [
    path("products/", ProductListView.as_view(), name="product-list"),
    path("products/<slug:slug>/", ProductDetailView.as_view(), name="product-detail"),
    path("categories/", CategoryTreeView.as_view(), name="category-tree"),
    path("brands/", BrandListView.as_view(), name="brand-list"),
    path("collections/<slug:slug>/", CollectionDetailView.as_view(), name="collection-detail"),
]
