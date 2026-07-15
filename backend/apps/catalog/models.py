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
    # M2M to Product added in Task 3 (after Product exists).

    def __str__(self) -> str:
        return self.name
