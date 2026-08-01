"""Content the marketing side of the business owns.

Plan-19a ships `Page` only. Banner, HomepageSection and MenuItem arrive in 19c — see the
plan for why the homepage builder is sequenced behind the things with launch consequences.
"""
from django.db import models
from django.utils.text import slugify

from apps.cms.sanitize import clean_html
from apps.core.models import TimeStampedModel


class Page(TimeStampedModel):
    """A standalone content page, addressed by the storefront at `/page/{slug}`.

    ── THE SLUG IS A PUBLISHED URL, NOT A LABEL ────────────────────────────────────

    `storefront/src/components/layout/Footer.tsx` hard-codes eleven of these slugs, and
    Plan-24's redirect map will point legacy WordPress URLs at them. So a slug is a
    promise: changing one breaks a live link, and deleting a page 404s a footer entry on
    a store taking money. Deletion is therefore not offered on the admin surface at all
    (`PageAdminViewSet` refuses DELETE); `status` is how a page stops being public.

    ── BODY IS STORED TWICE, ON PURPOSE ────────────────────────────────────────────

    `body_source` is exactly what the author submitted; `body` is that run through
    `cms.sanitize.clean_html`. Sanitising on write means the database holds only safe HTML
    so every reader is safe without repeating the rule — but it also means a mistake in the
    allow-list is baked into stored rows. Keeping the submission lets a corrected
    allow-list be re-applied without asking eleven pages to be retyped, and lets an author
    see that their `<iframe>` was dropped rather than silently losing it.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    STATUS_CHOICES = [(DRAFT, "Draft"), (PUBLISHED, "Published")]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    body_source = models.TextField(blank=True)
    body = models.TextField(blank=True, editable=False)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    seo_title = models.CharField(max_length=200, blank=True)
    seo_description = models.CharField(max_length=300, blank=True)
    # Ordering for any future "all pages" index; the footer's order is its own.
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "title"]

    def __str__(self) -> str:
        return f"{self.title} (/{self.slug})"

    @property
    def is_published(self) -> bool:
        return self.status == self.PUBLISHED

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:200]
        # DERIVED ON EVERY SAVE, never trusted from the caller: `body` is not a writable
        # serializer field anywhere, so the only way HTML reaches the storefront is
        # through this line.
        self.body = clean_html(self.body_source)
        super().save(*args, **kwargs)
