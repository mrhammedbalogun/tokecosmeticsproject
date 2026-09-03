"""Combos — several catalogue variants sold together at one price.

WHAT A COMBO IS NOT: a product. It has no SKU, no stock row and no variant of its own,
and that is the whole design. A combo that carried its own inventory would let the shop
sell twelve "Glow Kits" while holding four jars of the shea butter inside them; here the
components ARE the goods, so every existing guarantee — reservation, warehouse
allocation, the waybill's contents, the picker's list — keeps working untouched because
what reaches them is still `(ProductVariant, quantity)` pairs.

WHAT IT ADDS is a price. `ComboItem` names the variants and how many of each; the combo's
price in a market is either derived (`discount_percent` off what those components cost
there) or pinned (`ComboPrice`). The difference between the two numbers rides through the
cart and the order as its OWN discount line — `Totals.combo_discount`,
`Order.combo_discount_total` — beside the coupon and referral lines and for the same
reason they are separate: a customer reading a receipt needs to be told which saving is
which, and the shop needs to report on them apart.
"""
from django.db import models

from apps.core.models import TimeStampedModel

# Same reasoning as catalog.IMAGE_PATH_MAX: Django silently TRUNCATES a generated path
# that exceeds the field, and a truncated name breaks de-duplication rather than erroring.
IMAGE_PATH_MAX = 500

# The house default, and only a default. It prefills the admin's price box; what the
# customer pays is whatever that box ends up saying (see ComboPrice).
DEFAULT_DISCOUNT_PERCENT = 10


class Combo(TimeStampedModel):
    STATUS = [("draft", "Draft"), ("active", "Active"), ("archived", "Archived")]

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True)
    # Rich HTML, nh3-sanitised on the way in exactly like Product.description.
    description = models.TextField(blank=True)
    short_description = models.TextField(blank=True)
    # UNDER `catalog/`, like every other upload in this project, and that is not
    # cosmetic. The bucket is PRIVATE — the nightly Postgres dumps live in it under
    # `backups/` — so CloudFront reaches it through an Origin Access Control whose policy
    # is deliberately scoped to `catalog/*` and nothing else (see the storage block in
    # `config/settings/base.py`). An object written anywhere else uploads perfectly, is
    # listed perfectly, and then 403s at the CDN.
    #
    # This shipped as `upload_to="combos/"` and did exactly that: the first real combo's
    # featured image was a broken thumbnail in the admin. `apps/cms` had already been
    # through it, which is why its banners live at `catalog/cms-banners/` and not `cms/`.
    image = models.ImageField(
        upload_to="catalog/combos/", blank=True, null=True, max_length=IMAGE_PATH_MAX
    )
    status = models.CharField(max_length=10, choices=STATUS, default="draft")
    is_featured = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)
    # The working default the admin's pricing panel prefills each market with, and what
    # "Reset to N% off" recomputes from. NOT the price: a market with a `ComboPrice` row
    # ignores this entirely. Kept per-combo rather than global so a clearance bundle can
    # sit at 25% without moving every other combo.
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=DEFAULT_DISCOUNT_PERCENT
    )
    # Empty = every market, the same convention as Product.available_countries — see
    # apps/catalog/services.sellable_in, whose rule this deliberately mirrors.
    available_countries = models.ManyToManyField(
        "core.Country", blank=True, related_name="combos"
    )
    seo_title = models.CharField(max_length=255, blank=True)
    seo_description = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position", "-published_at", "name"]

    def __str__(self) -> str:
        return self.name


class ComboItem(TimeStampedModel):
    """One line of a combo: a specific variant, and how many of it are in the box.

    The FK is to a VARIANT, not a product, because that is the thing that has a price and
    a stock row. "Sample Product, 500g, pieces" is one variant; picking the product alone
    would leave the size and the pack unanswered, and the box has to contain something
    definite.

    PROTECT, not CASCADE. A variant sitting inside a live combo must not vanish because
    somebody pruned it from the product editor — the combo would silently start selling a
    smaller box at the same price. The variant delete then fails loudly, which is the
    point; `ProductVariantAdminViewSet.perform_destroy` already refuses deletes for
    reasons of its own and this is one more.
    """

    combo = models.ForeignKey(Combo, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.PROTECT, related_name="combo_items"
    )
    quantity = models.PositiveIntegerField(default=1)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["combo", "variant"], name="uniq_combo_variant"),
            models.CheckConstraint(
                check=models.Q(quantity__gte=1), name="combo_item_quantity_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quantity}x {self.variant.sku} in {self.combo.name}"


class ComboPrice(TimeStampedModel):
    """A PINNED price for one market. Its absence is meaningful: no row means the market
    is priced automatically, at `combo.discount_percent` off the live component total.

    Two modes rather than one because both are wanted and they answer different
    questions. Automatic keeps a combo honest for free — raise a component's price and
    the bundle follows, which is what a shop wants for the twenty combos nobody is
    watching. Pinned is for the one that was advertised at ₦18,000: that number must not
    move because a component was repriced, and it must not need a person to notice.

    No `currency` column. A market has exactly one currency (`Country.currency`), so a
    second column would only be a way for the two to disagree.
    """

    combo = models.ForeignKey(Combo, on_delete=models.CASCADE, related_name="prices")
    country = models.ForeignKey("core.Country", on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["combo", "country"], name="uniq_combo_price_market"),
        ]

    def __str__(self) -> str:
        return f"{self.combo.name} @ {self.country_id}: {self.amount}"
