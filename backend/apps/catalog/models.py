from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models.functions import Upper

from apps.core.models import TimeStampedModel

# Django's ImageField default is max_length=100, and Django does not raise when a
# generated path exceeds it -- the storage layer silently TRUNCATES the filename
# to fit. The migration importer saves to
# "catalog/products/<product-slug>/<attachment-id>-<filename>", and Product.slug
# alone is up to 280 characters, so 100 was never enough: 39 of the first 207
# imported images came back truncated. A truncated name still points at a real
# object, so nothing errors -- it just no longer matches the key the importer
# de-duplicates on, which would re-upload and duplicate those images on every
# subsequent run. 500 clears the worst case (17 + 280 + 1 + attachment id +
# filename) with room to spare; in Postgres a varchar length is only a check
# constraint, so widening costs nothing.
IMAGE_PATH_MAX = 500


class Category(TimeStampedModel):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to="catalog/categories/", blank=True, null=True, max_length=IMAGE_PATH_MAX
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    legacy_wp_id = models.IntegerField(null=True, blank=True, db_index=True)
    seo_title = models.CharField(max_length=255, blank=True)
    seo_description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["legacy_wp_id"],
                condition=models.Q(legacy_wp_id__isnull=False),
                name="uniq_category_legacy_wp_id",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def get_ancestors(self):
        """Root-first list of ancestors (excludes self). Depth is small (<= 3).

        TERMINATES ON A CYCLE rather than spinning forever. `CategoryAdminSerializer`
        refuses to create one (Plan-17a Task 10), but this is the storefront's
        breadcrumb walk and it must not be the thing that hangs a web worker if a bad
        parent ever reaches the table another way — a direct database edit, a fixture,
        or a row written before that validator existed. Stopping early yields a short
        breadcrumb; not stopping yields an unresponsive process.
        """
        chain = []
        seen = set()
        node = self.parent
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            chain.append(node)
            node = node.parent
        return list(reversed(chain))


class Brand(TimeStampedModel):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    logo = models.ImageField(
        upload_to="catalog/brands/", blank=True, null=True, max_length=IMAGE_PATH_MAX
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Tag(TimeStampedModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)

    def __str__(self) -> str:
        return self.name


class Collection(TimeStampedModel):
    RULES = [
        ("manual", "Manual"),
        ("new_arrivals", "New arrivals"),
        ("best_sellers", "Best sellers"),
        ("trending", "Trending"),
    ]

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to="catalog/collections/", blank=True, null=True, max_length=IMAGE_PATH_MAX
    )
    is_active = models.BooleanField(default=True)
    rule = models.CharField(max_length=20, choices=RULES, default="manual")
    products = models.ManyToManyField("Product", blank=True, related_name="collections")

    def __str__(self) -> str:
        return self.name


class Product(TimeStampedModel):
    STATUS = [("draft", "Draft"), ("active", "Active"), ("archived", "Archived")]
    # The `audience` vocabulary. The admin UI's checkboxes and the serializer's
    # validation both derive from this list; add here first.
    AUDIENCE_CHOICES = ["male", "female", "baby"]

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True)
    brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )
    categories = models.ManyToManyField(Category, blank=True, related_name="products")
    tags = models.ManyToManyField(Tag, blank=True, related_name="products")
    description = models.TextField(blank=True)          # rich HTML
    short_description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default="draft")
    is_featured = models.BooleanField(default=False)
    # Denormalised from APPROVED reviews only (apps.reviews.services.recompute_product_rating).
    # Never hand-write these — a read must never aggregate reviews. rating_avg is 0.00
    # with rating_count 0 until the first review is approved.
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField(default=0)
    ingredients = models.TextField(blank=True)
    directions = models.TextField(blank=True)
    warnings = models.TextField(blank=True)
    # Who the product is for: a subset of {"male", "female", "baby"} (AUDIENCE_CHOICES).
    # A set, not a choice — one product is routinely for several. Empty means "not
    # stated", never "for nobody". Exists for filtering and AI product recommendation.
    audience = models.JSONField(default=list, blank=True)
    specs = models.JSONField(default=list, blank=True)  # [{"label": .., "value": ..}]
    faqs = models.JSONField(default=list, blank=True)   # [{"q": .., "a": ..}]
    related = models.ManyToManyField("self", blank=True)
    available_countries = models.ManyToManyField(
        "core.Country", blank=True, related_name="products"
    )  # empty = everywhere (see Plan-05b sellable_in)
    seo_title = models.CharField(max_length=255, blank=True)
    seo_description = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    legacy_source = models.CharField(max_length=50, blank=True)
    legacy_wp_id = models.IntegerField(null=True, blank=True)
    # Plan-21: marketing content migrated from WooCommerce ACF fields.
    # usps: ["Daily hydration, all-day softness.", ...]
    usps = models.JSONField(default=list, blank=True)
    # testimonials: [{"name":.., "text":.., "skin_concern":.., "qty_bought":..}]
    # NOT reviews — these carry no rating and must never touch rating_avg/rating_count
    # or the schema.org aggregateRating in storefront/src/lib/seo.ts.
    testimonials = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-published_at", "name"]
        indexes = [
            # Bare column, used by the STOREFRONT's `TrigramSimilarity("name", q)` ranking
            # (apps/search/backends.py). Kept as-is.
            #
            # IT DOES NOT SERVE `name__icontains`, verified by EXPLAIN in Plan-16 Task 6:
            # Django compiles that lookup to `UPPER(name::text) LIKE UPPER(%s)`, and an
            # index on the bare column is simply never consulted for it (200k rows: 88.7ms
            # unindexed, 89.1ms with the bare index). Hence the second index below rather
            # than an edit to this one — the two lookups need two different expressions.
            GinIndex(name="product_name_trgm", fields=["name"], opclasses=["gin_trgm_ops"]),
            GinIndex(OpClass(Upper("name"), name="gin_trgm_ops"), name="product_name_upper_trgm"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["legacy_source", "legacy_wp_id"],
                condition=models.Q(legacy_wp_id__isnull=False),
                name="uniq_product_legacy_ref",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=64, unique=True)
    barcode = models.CharField(max_length=64, blank=True)
    name = models.CharField(max_length=120)             # e.g. "50ml"
    option_values = models.JSONField(default=dict, blank=True)  # {"Size": "50ml"}
    weight_grams = models.PositiveIntegerField(null=True, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        indexes = [
            # SKU lookup from the admin search box. `sku` is already UNIQUE, and that btree
            # cannot serve `%term%` — staff type the middle of a SKU as often as the start.
            # On `UPPER(sku)` for the same reason as everywhere else: that is the
            # expression Django's `icontains` compiles to (Plan-16 Task 6).
            GinIndex(OpClass(Upper("sku"), name="gin_trgm_ops"), name="variant_sku_trgm"),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} — {self.name}"


class ProductImage(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="catalog/products/", max_length=IMAGE_PATH_MAX)
    alt = models.CharField(max_length=255, blank=True)
    position = models.PositiveIntegerField(default=0)
    variant = models.ForeignKey(
        "ProductVariant", null=True, blank=True, on_delete=models.SET_NULL, related_name="images"
    )

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.product.name} image #{self.position}"


class ProductVideo(TimeStampedModel):
    """A product's video, as a pointer into the cms media library.

    The original model (0003) carried a bare `url` for YouTube-style embeds; nothing —
    no importer, no admin surface, no storefront serializer — ever wrote or read it, so
    0010 dropped it against an empty table rather than shipping a field whose rows the
    storefront would silently never render. When embeds are wanted, add `embed_url`
    TOGETHER WITH its renderer.

    `asset` reaches across into cms — layering debt, accepted knowingly: the library and
    its presigned-upload pipeline live there, and extracting a shared `media` app would
    mean moving a model across apps on a live database. PROTECT for the same reason
    banners use it: when asset deletion ships, "still in use by product X" can be
    refused by construction.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="videos")
    asset = models.ForeignKey(
        "cms.MediaAsset", on_delete=models.PROTECT, related_name="product_videos"
    )
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.product.name} video #{self.position}"
