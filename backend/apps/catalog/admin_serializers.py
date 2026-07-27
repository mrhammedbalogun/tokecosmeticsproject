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
    # Declared explicitly with defaults so they land in `attrs` even when omitted from
    # the request. Product.Meta has a 2-field partial UniqueConstraint
    # (legacy_source, legacy_wp_id) for Plan-21 migration idempotency; DRF auto-generates
    # a UniqueTogetherValidator from any multi-field UniqueConstraint, and that validator
    # always treats its fields as required on create UNLESS they already appear in attrs
    # via a serializer-level default (see DRF docs: "Note" under UniqueTogetherValidator).
    # Without this, staff creating a product from the admin UI (which never sends these
    # migration-only fields) would get "This field is required."
    legacy_source = serializers.CharField(required=False, default="")
    legacy_wp_id = serializers.IntegerField(required=False, allow_null=True, default=None)

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


class ProductImageAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "product", "image", "alt", "position", "variant"]
        read_only_fields = ["product"]
