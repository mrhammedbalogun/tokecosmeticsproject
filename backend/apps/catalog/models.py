from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.core.models import TimeStampedModel


class Category(TimeStampedModel):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="catalog/categories/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    seo_title = models.CharField(max_length=255, blank=True)
    seo_description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name

    def get_ancestors(self):
        """Root-first list of ancestors (excludes self). Depth is small (<= 3)."""
        chain = []
        node = self.parent
        while node is not None:
            chain.append(node)
            node = node.parent
        return list(reversed(chain))


class Brand(TimeStampedModel):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    logo = models.ImageField(upload_to="catalog/brands/", blank=True, null=True)
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
    image = models.ImageField(upload_to="catalog/collections/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    rule = models.CharField(max_length=20, choices=RULES, default="manual")
    products = models.ManyToManyField("Product", blank=True, related_name="collections")

    def __str__(self) -> str:
        return self.name


class Product(TimeStampedModel):
    STATUS = [("draft", "Draft"), ("active", "Active"), ("archived", "Archived")]

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
    ingredients = models.TextField(blank=True)
    directions = models.TextField(blank=True)
    warnings = models.TextField(blank=True)
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

    class Meta:
        ordering = ["-published_at", "name"]
        indexes = [
            GinIndex(name="product_name_trgm", fields=["name"], opclasses=["gin_trgm_ops"]),
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

    def __str__(self) -> str:
        return f"{self.product.name} — {self.name}"


class ProductImage(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="catalog/products/")
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
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="videos")
    url = models.URLField()
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.product.name} video #{self.position}"
