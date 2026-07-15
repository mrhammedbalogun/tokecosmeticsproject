from django.contrib import admin

from apps.catalog.models import (
    Brand,
    Category,
    Collection,
    Product,
    ProductImage,
    ProductVariant,
    ProductVideo,
    Tag,
)


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "brand", "status", "is_featured")
    list_filter = ("status", "is_featured", "brand")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductVariantInline, ProductImageInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent", "is_active", "sort_order")
    prepopulated_fields = {"slug": ("name",)}


admin.site.register([Brand, Tag, Collection, ProductVideo])
