from decimal import Decimal

from rest_framework import serializers

from apps.catalog.models import Brand, Category, Collection, Product, ProductVariant
from apps.pricing.services import resolve_price


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["name", "slug", "logo", "description"]


class CategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["name", "slug", "image", "sort_order", "children"]

    def get_children(self, obj):
        kids = [c for c in obj.children.all() if c.is_active]
        return CategorySerializer(kids, many=True, context=self.context).data


class VariantSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = ["sku", "name", "option_values", "price", "in_stock"]

    def get_price(self, obj):
        country = self.context["request"].country
        rp = resolve_price(obj, country)
        if rp is None:
            return None
        return {
            "amount": str(rp.amount),
            "compare_at": str(rp.compare_at) if rp.compare_at is not None else None,
            "currency": rp.currency,
            "tax_rate": str(rp.tax_rate),
            "prices_include_tax": rp.prices_include_tax,
        }

    def get_in_stock(self, obj):
        return True  # PLAN-06: real stock from inventory.available_qty > 0


class ProductListSerializer(serializers.ModelSerializer):
    from_price = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()
    brand = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ["name", "slug", "brand", "is_featured", "from_price", "currency", "image"]

    def get_from_price(self, obj):
        amount = getattr(obj, "min_price", None)
        if amount is None:
            return None
        # Subquery annotations skip the field's decimal quantization — format to the
        # currency's decimal places so the "from price" matches the detail price.
        dp = self.context["request"].country.currency.decimal_places
        quantum = Decimal(1).scaleb(-dp)  # dp=2 -> 0.01
        return str(Decimal(str(amount)).quantize(quantum))

    def get_currency(self, obj):
        return self.context["request"].country.currency.code

    def get_image(self, obj):
        first = obj.images.all()[:1]
        return first[0].image.url if first else None


class ProductDetailSerializer(serializers.ModelSerializer):
    brand = BrandSerializer(read_only=True)
    variants = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "name", "slug", "brand", "description", "short_description",
            "ingredients", "directions", "warnings", "specs", "faqs",
            "seo_title", "seo_description", "variants", "images", "related",
        ]

    def get_variants(self, obj):
        active = obj.variants.filter(is_active=True)
        return VariantSerializer(active, many=True, context=self.context).data

    def get_images(self, obj):
        return [{"url": i.image.url, "alt": i.alt} for i in obj.images.all()]

    def get_related(self, obj):
        from apps.catalog.services import annotate_min_price, sellable_in

        country = self.context["request"].country
        sellable = [p for p in obj.related.all() if sellable_in(p, country)]
        pks = [p.pk for p in sellable]
        qs = annotate_min_price(Product.objects.filter(pk__in=pks), country).prefetch_related(
            "images"
        ).select_related("brand")
        return ProductListSerializer(qs, many=True, context=self.context).data


class CollectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Collection
        fields = ["name", "slug", "description", "image"]
