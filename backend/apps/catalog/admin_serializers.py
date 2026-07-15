from rest_framework import serializers

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


from apps.pricing.models import Price


class ProductAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "brand", "categories", "tags", "description",
            "short_description", "status", "is_featured", "ingredients", "directions",
            "warnings", "specs", "faqs", "related", "available_countries",
            "seo_title", "seo_description", "published_at", "legacy_source", "legacy_wp_id",
        ]


class CategoryAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = "__all__"


class BrandAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = "__all__"


class TagAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = "__all__"


class CollectionAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Collection
        fields = "__all__"


class ProductVariantAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = "__all__"


class ProductVideoAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVideo
        fields = "__all__"


class PriceAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Price
        fields = "__all__"
