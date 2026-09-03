"""Serializers for the combo admin surface.

Every serializer carries an `audit_allowlist` for the same reason the catalogue's do —
`apps/core/audit.py` writes only the keys named there. Long prose (`description`,
`short_description`) and the uploaded `image` are excluded on the same grounds: the copy
would blow the 8KB per-row cap and take the whole field list down into a truncation
marker, and an `UploadedFile` would be stored as a filename with no evidentiary value.
"""
from decimal import Decimal

from rest_framework import serializers

from apps.catalog.images import storage_url, variant_image_path
from apps.catalog.models import ProductVariant
from apps.cms.sanitize import clean_html
from apps.combos.models import Combo, ComboItem, ComboPrice
from apps.combos.services import available_in, resolve_combo_price
from apps.core.models import Country
from apps.pricing.services import resolve_price

COMBO_HTML_FIELDS = ("description", "short_description")

# How many of one product may go in a box. A ceiling rather than no ceiling because the
# money columns are `max_digits=12` — ₦9,999,999,999.99 — and quantity is the one input
# that multiplies a price without bound. A quantity of 999,999,999 prices a bundle at
# ₦18.5 TRILLION, which is accepted here, shown in the shop, and then raises `DataError`
# from Postgres when `place_order` writes `Order.subtotal` — inside the locked
# transaction, which is a 500 handed to a customer at the till. 100 is far above any real
# bundle and far below the overflow.
MAX_ITEM_QUANTITY = 100


def variant_prices(variant) -> dict:
    """{"NG": "12000.00", "GB": null, …} for every active market.

    The admin's pricing panel adds these up live as items are picked, which is what makes
    "components total → 10% off → your price" appear without a round trip per keystroke.
    `null` for a market the variant is not priced in is the load-bearing case: it is what
    the panel turns into "this combo cannot be sold in the UK yet", which is a far more
    useful thing to be told at build time than at publish time.
    """
    out = {}
    for country in Country.objects.filter(is_active=True).select_related("currency"):
        resolved = resolve_price(variant, country)
        out[country.code] = str(resolved.amount) if resolved else None
    return out


class ComboItemAdminSerializer(serializers.ModelSerializer):
    """One picked variant, with everything the builder row needs to draw itself."""

    variant = serializers.PrimaryKeyRelatedField(queryset=ProductVariant.objects.all())
    product_name = serializers.CharField(source="variant.product.name", read_only=True)
    product_slug = serializers.CharField(source="variant.product.slug", read_only=True)
    variant_name = serializers.CharField(source="variant.name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    option_values = serializers.JSONField(source="variant.option_values", read_only=True)
    image = serializers.SerializerMethodField()
    prices = serializers.SerializerMethodField()

    class Meta:
        model = ComboItem
        fields = ["id", "variant", "quantity", "position", "product_name", "product_slug",
                  "variant_name", "sku", "option_values", "image", "prices"]

    def get_image(self, obj) -> str | None:
        return storage_url(variant_image_path(obj.variant)) or None

    def get_prices(self, obj) -> dict:
        return variant_prices(obj.variant)


class ComboPriceAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComboPrice
        fields = ["country", "amount"]


class ComboAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = (
        "name", "slug", "status", "is_featured", "position", "discount_percent",
        "available_countries", "seo_title", "seo_description", "published_at",
        "items", "prices",
    )

    # WRITTEN WHOLE, not patched line by line. The builder is one screen with a list on
    # it; a shopper-visible bundle whose contents were assembled by four separate
    # requests can be half-saved, and a half-saved combo is one that prices wrong. The
    # nested writes below replace the sets outright inside the audit mixin's transaction.
    items = ComboItemAdminSerializer(many=True, required=False)
    prices = ComboPriceAdminSerializer(many=True, required=False)
    image_url = serializers.SerializerMethodField()
    # What the combo actually costs in each market TODAY, derived — the editor renders it
    # so the person setting a price is looking at the same number the storefront will
    # show, rather than at their own arithmetic.
    pricing = serializers.SerializerMethodField()
    # Whether the shop would actually SHOW it, per market, and why not. Separate from
    # `pricing` because the two can disagree: a bundle holding a switched-off variant
    # still prices perfectly and is still refused by `available_in` — so a builder
    # reading `pricing` alone sees "₦78,480" for something no customer can ever see.
    live = serializers.SerializerMethodField()
    blockers = serializers.SerializerMethodField()

    class Meta:
        model = Combo
        fields = ["id", "name", "slug", "description", "short_description", "status",
                  "is_featured", "position", "discount_percent", "available_countries",
                  "seo_title", "seo_description", "published_at", "image", "image_url",
                  "items", "prices", "pricing", "live", "blockers",
                  "created_at", "updated_at"]
        extra_kwargs = {"image": {"write_only": True, "required": False}}

    def get_image_url(self, obj) -> str | None:
        return storage_url(obj.image.name) if obj.image else None

    def get_pricing(self, obj) -> dict:
        """Per-market {components_total, amount, saving, saving_percent, pinned}, or a
        `null` entry for a market the combo cannot be priced in at all."""
        out = {}
        for country in Country.objects.filter(is_active=True).select_related("currency"):
            p = resolve_combo_price(obj, country)
            out[country.code] = None if p is None else {
                "components_total": str(p.components_total),
                "amount": str(p.amount),
                "saving": str(p.saving),
                "saving_percent": str(p.saving_percent),
                "currency": p.currency,
                "pinned": p.pinned,
            }
        return out

    def get_live(self, obj) -> dict:
        return {
            country.code: available_in(obj, country)
            for country in Country.objects.filter(is_active=True).select_related("currency")
        }

    def get_blockers(self, obj) -> list[str]:
        """Market-INDEPENDENT reasons this bundle is not on sale, in plain sentences.

        Per-market problems (a component with no price in the UK) stay in the pricing
        panel, which already has a row to put them on. What lands here is everything that
        would keep the combo dark in EVERY market — the class of problem a curator can
        stare at a healthy-looking price panel and never notice.
        """
        reasons = []
        if not obj.items.exists():
            reasons.append("There is nothing in the box yet.")
        for item in obj.items.all():
            variant = item.variant
            if not variant.is_active:
                reasons.append(
                    f"{variant.product.name} ({variant.sku}) is switched off, so it "
                    "cannot be sold."
                )
            elif variant.product.status != "active":
                reasons.append(
                    f"{variant.product.name} is a {variant.product.status} product, so "
                    "it is not on sale yet."
                )
        if obj.status != "active" and not reasons:
            # Said last and only when nothing else is wrong: "it is a draft" is the one
            # blocker the curator already knows about, and leading with it would bury the
            # ones they do not.
            reasons.append("This combo is still a draft — set it to Active to publish it.")
        return reasons

    def validate(self, attrs):
        for field in COMBO_HTML_FIELDS:
            if field in attrs:
                attrs[field] = clean_html(attrs[field])
        return attrs

    def validate_items(self, value):
        """Everything the database would otherwise answer with a 500.

        Each rule below maps to a constraint or a column limit that DOES hold — the point
        is to reach it as a 400 naming the row rather than as an IntegrityError, which
        reaches the curator as "something went wrong" and reaches Sentry as noise.
        """
        seen = set()
        for row in value:
            variant = row["variant"]
            # A variant twice in one bundle is the "meant to raise the quantity" mistake,
            # and `uniq_combo_variant` would answer it with an IntegrityError 500.
            if variant.pk in seen:
                raise serializers.ValidationError(
                    f"{variant.sku} is in this combo twice — raise its quantity instead."
                )
            seen.add(variant.pk)

            quantity = row.get("quantity", 1)
            # `combo_item_quantity_positive` (a CHECK constraint) would raise here.
            if quantity < 1:
                raise serializers.ValidationError(
                    f"{variant.sku}: a combo cannot contain zero of something. "
                    "Remove the row instead."
                )
            if quantity > MAX_ITEM_QUANTITY:
                raise serializers.ValidationError(
                    f"{variant.sku}: {MAX_ITEM_QUANTITY} is the most of one product a "
                    "combo can hold."
                )

            # A variant the merchant switched off can never be sold — the standalone
            # add-to-cart path refuses it outright — so a bundle containing one would be
            # a bundle that silently never appears. Refused at build time, where there is
            # somebody to tell. A DRAFT product is deliberately still allowed: bundles get
            # built ahead of a launch, and `available_in` keeps that one off the shelf
            # until the product goes live.
            if not variant.is_active:
                raise serializers.ValidationError(
                    f"{variant.sku} is switched off, so it cannot be sold in a combo. "
                    "Re-activate the variant first."
                )
        return value

    def validate_prices(self, value):
        seen = set()
        for row in value:
            country = row["country"]
            # `uniq_combo_price_market` would answer this with an IntegrityError 500.
            if country.pk in seen:
                raise serializers.ValidationError(
                    f"{country.pk} has two prices. Give it one."
                )
            seen.add(country.pk)
            # A negative pin is CLAMPED to zero by `resolve_combo_price` rather than
            # rejected there, because that function must never hand the shop a negative
            # price. Clamping means a typed "-500" ships as a FREE combo, silently. This
            # is the only place it can be refused while somebody is still looking at it.
            if row["amount"] < 0:
                raise serializers.ValidationError(
                    f"{country.pk}: a price cannot be negative."
                )
        return value

    def validate_discount_percent(self, value):
        if not (Decimal("0") <= Decimal(value) <= Decimal("100")):
            raise serializers.ValidationError("Must be between 0 and 100.")
        return value

    def create(self, validated_data):
        items = validated_data.pop("items", [])
        prices = validated_data.pop("prices", [])
        countries = validated_data.pop("available_countries", None)
        combo = Combo.objects.create(**validated_data)
        if countries is not None:
            combo.available_countries.set(countries)
        self._write_children(combo, items, prices)
        return combo

    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        prices = validated_data.pop("prices", None)
        countries = validated_data.pop("available_countries", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if countries is not None:
            instance.available_countries.set(countries)
        self._write_children(instance, items, prices)
        return instance

    @staticmethod
    def _write_children(combo, items, prices):
        """Replace the item and price sets wholesale when they were sent.

        `None` means "not sent, leave alone" — so a PATCH that flips `status` to active
        does not silently empty the bundle. An empty LIST means "sent, and it is empty",
        which is a real thing an editor can do.
        """
        if items is not None:
            combo.items.all().delete()
            ComboItem.objects.bulk_create([
                ComboItem(
                    combo=combo, variant=row["variant"],
                    quantity=row.get("quantity", 1), position=index,
                )
                for index, row in enumerate(items)
            ])
        if prices is not None:
            combo.prices.all().delete()
            ComboPrice.objects.bulk_create([
                ComboPrice(combo=combo, country=row["country"], amount=row["amount"])
                for row in prices
            ])


class ComboListAdminSerializer(serializers.ModelSerializer):
    """The list row: enough to recognise a bundle and see whether it is sellable."""

    image_url = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()
    markets = serializers.SerializerMethodField()

    class Meta:
        model = Combo
        fields = ["id", "name", "slug", "status", "is_featured", "position",
                  "discount_percent", "image_url", "item_count", "markets", "updated_at"]

    def get_image_url(self, obj) -> str | None:
        return storage_url(obj.image.name) if obj.image else None

    def get_item_count(self, obj) -> int:
        return len(obj.items.all())

    def get_markets(self, obj) -> list[str]:
        codes = [c.code for c in obj.available_countries.all()]
        # Empty means everywhere (Combo.available_countries), and the list has to say so
        # in words — a blank cell reads as "nowhere", which is the opposite.
        return sorted(codes)


class ProductPickerSerializer(serializers.Serializer):
    """A search hit in the builder's product box: the product, its picture, and every
    variant it could contribute — priced per market, so picking one updates the total
    without another round trip."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.SlugField()
    image = serializers.SerializerMethodField()
    variants = serializers.SerializerMethodField()

    def get_image(self, obj) -> str | None:
        images = list(obj.images.all())
        return storage_url(images[0].thumbnail.name or images[0].image.name) if images else None

    def get_variants(self, obj) -> list[dict]:
        return [
            {
                "id": v.id,
                "name": v.name,
                "sku": v.sku,
                "option_values": v.option_values or {},
                "image": storage_url(variant_image_path(v)) or None,
                "prices": variant_prices(v),
            }
            for v in obj.variants.all()
            if v.is_active
        ]
