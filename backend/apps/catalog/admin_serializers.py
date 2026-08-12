"""Serializers for the catalogue admin surface.

EVERY serializer here carries an `audit_allowlist`: the exact request-body keys that
Plan-16 Task 4's `AuditLog.changes` may store. Anything not named is never written,
which is the whole answer to "what stops a secret-shaped field ending up in the audit
table" (`apps/core/audit.py` argues why an allowlist rather than a denylist, and
`apps/core/tests/test_audit_guard.py` refuses any entry that names a `write_only`
field -- the one category most likely to be a credential).

TWO OMISSIONS ARE DELIBERATE AND ARE NOT OVERSIGHTS:

* **Long prose is excluded** -- `description`, `ingredients`, `directions`, `warnings`,
  `specs`, `faqs`. Each can be kilobytes on its own, and a single one of them would
  blow the 8KB per-row cap and take the whole row's field list down with it into a
  truncation marker. What an audit trail needs from a product edit is which of the
  consequential fields moved (name, slug, status, brand, availability), not the copy.
* **Uploaded files are excluded** -- `image`, `logo`. `request.data` holds an
  `UploadedFile` there, so the stored value would be a filename: no evidentiary value,
  and it invites somebody to later assume the file itself was captured.
"""
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
    audit_allowlist = (
        "name", "slug", "brand", "categories", "tags", "status", "is_featured",
        "related", "available_countries", "seo_title", "seo_description",
        "published_at", "legacy_source", "legacy_wp_id",
    )

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

    # --- read-only, for the admin products LIST (Plan-17a Task 2) --------------------
    #
    # The list has to answer "which product is this, and what still needs doing to it"
    # at a glance, and none of that was expressible: the serializer carried no image, no
    # variant count, no indication of which markets a product is priced for, and not even
    # `updated_at`. Staff would have had to open every product to find the one they meant.
    #
    # ALL THREE ARE SerializerMethodFields READING PREFETCHED RELATIONS, deliberately, and
    # NOT queryset annotations. An annotated field renders fine on a list and then raises
    # AttributeError on the POST/PATCH response, because the instance the write returns is
    # a plain model with no annotation attached. `len(obj.images.all())` is free when the
    # viewset prefetched (the list) and costs one query when it did not (a create), which
    # is the right trade in both directions.
    thumbnail = serializers.SerializerMethodField()
    variant_count = serializers.SerializerMethodField()
    priced_currencies = serializers.SerializerMethodField()

    def get_thumbnail(self, obj) -> str | None:
        # ProductImage.Meta orders on ["position", "id"], so "first" is the gallery's
        # first — the same image the storefront leads with, which is what makes the row
        # recognisable to somebody who knows the shelf rather than the SKU.
        images = list(obj.images.all())
        return images[0].image.url if images else None

    def get_variant_count(self, obj) -> int:
        return len(obj.variants.all())

    def get_priced_currencies(self, obj) -> list[str]:
        """Which currencies this product has ANY price in, so the list can flag the ones
        that are invisible in a market for want of a price.

        Currency-level rows only (`country is None`). A country override is a narrower
        statement than "this product is priced in GBP" and reading it as the same thing
        would show a product as priced for a market it is still hidden in. Overrides are
        17c; production has none today, and this must not be the code that assumes so.
        """
        codes = {
            price.currency_id
            for variant in obj.variants.all()
            for price in variant.prices.all()
            if price.country_id is None
        }
        return sorted(codes)

    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "brand", "categories", "tags", "description",
            "short_description", "status", "is_featured", "ingredients", "directions",
            "warnings", "specs", "faqs", "related", "available_countries",
            "seo_title", "seo_description", "published_at", "legacy_source", "legacy_wp_id",
            "updated_at", "thumbnail", "variant_count", "priced_currencies",
        ]
        read_only_fields = ["updated_at"]


class CategoryAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = ("name", "slug", "parent", "is_active", "sort_order", "seo_title", "seo_description")

    class Meta:
        model = Category
        fields = "__all__"

    def validate_parent(self, value):
        """Refuse a parent that would put a category inside its own subtree.

        ── WHY THIS IS NOT COSMETIC ────────────────────────────────────────────────

        Nothing else stops it. `Category.parent` is a plain self-FK with no `clean()`
        and no database constraint, so before Plan-17a Task 10 a single PATCH could
        make a category its own ancestor. Two things then hang, both on the PUBLIC
        storefront rather than here:

        * `Category.get_ancestors()` walks `node = node.parent` with no termination
          condition but `None` — a cycle spins forever. It backs the PDP breadcrumb.
        * `api_serializers.CategorySerializer.get_children` recurses into itself, so
          the category tree endpoint blows the stack.

        A hung worker is a worse outcome than any bad tree shape, and the admin UI is
        what would have made it reachable — the tree page offers a parent select on
        all 40 categories.

        Checked here rather than in `validate()` so the message lands on the `parent`
        field, which is the control the operator is looking at.
        """
        if value is None:
            return value

        instance = self.instance
        # On create there is no subtree yet, so any existing parent is fine.
        if instance is None or instance.pk is None:
            return value

        if value.pk == instance.pk:
            raise serializers.ValidationError("A category cannot be its own parent.")

        # Walk up from the proposed parent. Meeting `instance` means the proposed
        # parent sits inside this category's own subtree.
        #
        # `seen` guards the walk itself: if the data ALREADY holds a cycle (written
        # before this validator existed, or straight into the database), an unguarded
        # loop here would hang the very request that was trying to fix it.
        seen: set[int] = set()
        node = value
        while node is not None and node.pk not in seen:
            if node.pk == instance.pk:
                raise serializers.ValidationError(
                    f"“{value.name}” is inside “{instance.name}”, so it cannot also be "
                    "its parent."
                )
            seen.add(node.pk)
            node = node.parent

        return value


class BrandAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = ("name", "slug", "is_active")

    class Meta:
        model = Brand
        fields = "__all__"


class TagAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = ("name", "slug")

    class Meta:
        model = Tag
        fields = "__all__"


class CollectionAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = ("name", "slug", "is_active", "rule", "products")

    class Meta:
        model = Collection
        fields = "__all__"


class ProductVariantAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = (
        "product", "sku", "barcode", "name", "option_values", "weight_grams",
        "is_default", "is_active", "position",
    )

    class Meta:
        model = ProductVariant
        fields = "__all__"


class ProductVideoAdminSerializer(serializers.ModelSerializer):
    """A video slot on a product: a library binding, not an upload.

    The bytes never pass through this serializer — they go browser → S3 via the cms
    video-ticket/finalize pair (Vercel kills request bodies over ~4.5MB, so a relayed
    video cannot arrive). What is written here is the ATTACH: which finalized library
    asset plays on which product. `file` is the asset's URL, read-only, so the admin's
    Videos tab can preview rows without a second fetch.
    """

    audit_allowlist = ("product", "asset", "position")

    file = serializers.FileField(source="asset.file", read_only=True)

    class Meta:
        model = ProductVideo
        fields = ["id", "product", "asset", "position", "file"]

    def validate_asset(self, asset):
        # `kind` was sniffed from the bytes at upload, so this check is real: an image
        # asset behind a <video> tag renders a permanently black player.
        if asset.kind != asset.VIDEO:
            raise serializers.ValidationError("That library file is an image, not a video.")
        return asset

    def validate_product(self, product):
        # Create binds the product; PATCH must not quietly move a video onto another
        # product — same rule ProductImage enforces by making `product` read-only.
        # It cannot be read-only HERE because this JSON route has no URL to bind from.
        if self.instance is not None and product != self.instance.product:
            raise serializers.ValidationError(
                "A video cannot be moved to another product — delete and re-attach."
            )
        return product


class PriceAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = (
        "variant", "currency", "country", "amount", "compare_at_amount",
        "starts_at", "ends_at",
    )

    class Meta:
        model = Price
        fields = "__all__"


class ProductImageAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = ("product", "alt", "position", "variant")

    class Meta:
        model = ProductImage
        fields = ["id", "product", "image", "alt", "position", "variant"]
        read_only_fields = ["product"]
