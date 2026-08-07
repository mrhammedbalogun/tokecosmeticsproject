"""Content the marketing side of the business owns.

Plan-19a ships `Page` only. Banner, HomepageSection and MenuItem arrive in 19c — see the
plan for why the homepage builder is sequenced behind the things with launch consequences.
"""
from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.cms.sanitize import clean_html
from apps.core.models import TimeStampedModel


class MediaAsset(TimeStampedModel):
    """One reusable file in the media library (2026-08-07).

    Before this model, every upload was born attached to one banner and reusing an image
    meant uploading it again — the library makes an upload a fact of its own that any
    number of tiles can point at. Files land under `catalog/library/` because Hammed's
    standing ruling is that all media lives in the Toke S3 bucket and CloudFront serves
    only the `catalog/` prefix.

    `kind` is derived SERVER-SIDE at upload (Pillow sniff for images), never taken from
    the client's Content-Type — it is what lets banner attachment refuse an .mp4 behind
    an `<img>`. NO DELETE in v1: banners reference assets with `on_delete=PROTECT`, so
    when deletion arrives it can refuse "still in use" by construction instead of by
    string-scanning media columns. Nothing here (or anywhere in the project) deletes the
    underlying S3 object, so two rows sharing one file is safe.
    """

    IMAGE = "image"
    VIDEO = "video"
    KIND_CHOICES = [(IMAGE, "Image"), (VIDEO, "Video")]

    file = models.FileField(upload_to="catalog/library/", max_length=300)
    kind = models.CharField(max_length=5, choices=KIND_CHOICES)
    # What the uploader called it — `file.name` gets uniqued by storage, and the picker
    # searches on the human name.
    original_name = models.CharField(max_length=255, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="media_assets",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.original_name or self.file.name} ({self.kind})"


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


class Banner(TimeStampedModel):
    """A promotional strip or hero card.

    `marketing.manage`, NOT `cms.manage` — `rbac.py` argues this out: a banner announces a
    promotion, so a campaign that cannot be announced cannot run, and the promo rail is
    campaign material rather than the legally load-bearing pages `cms.manage` protects.

    NO HTML ANYWHERE. Every field here is plain text that React escapes on render, so this
    model adds no new XSS surface — unlike `Page.body`, which needs the sanitiser. Keep it
    that way: a `body`-style rich field on a banner would need the same treatment.
    """

    HERO = "hero"
    STRIP = "strip"
    CATEGORY = "category"
    # Landing redesign (2026-08-05): every homepage tile is a Banner with a placement,
    # so one manager edits the whole page and every tile gets image/video + CTA +
    # scheduling for free. Multi-tile placements (category ×4, concern ×3, trio ×3)
    # order by `sort`; the storefront falls back to its built-in tile when a placement
    # has no live banner — an empty CMS never blanks a section.
    PLACEMENT_CHOICES = [
        (HERO, "Hero slide"),
        (STRIP, "News marquee item"),
        (CATEGORY, "Shop-by-category tile"),
        ("concern", "Shop-by-concern tile"),
        ("feature", "Glow Set feature"),
        ("feature_nature", "tokè × natural tile"),
        ("feature_collection", "Toke Naturals tile"),
        ("men", "Men section banner"),
        ("women", "Women section banner"),
        ("babies", "Babies section banner"),
        ("tiktok", "TikTok section banner"),
        ("trio", "Collections trio tile"),
    ]

    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=300, blank=True)
    image = models.ImageField(upload_to="catalog/cms-banners/", blank=True)
    mobile_image = models.ImageField(upload_to="catalog/cms-banners/", blank=True)
    cta_text = models.CharField(max_length=60, blank=True)
    cta_url = models.CharField(max_length=300, blank=True)
    # Landing redesign (2026-08-04, amended same day): a HERO banner may be a video.
    # An UPLOAD, like the images — Hammed's ruling: all media lives in the Toke S3
    # bucket, so marketers upload the file and django-storages puts it beside the
    # banner artwork. The storefront renders <video autoplay muted loop> with the
    # image (if any) as poster; no media-type tag is ever shown to customers.
    video = models.FileField(upload_to="catalog/cms-banners/", blank=True)
    # Media-library bindings (2026-08-07). The FileFields above remain what the
    # storefront renders; these record WHERE the file came from when it was a library
    # pick, so "which tiles use this asset?" is a reverse relation rather than a string
    # scan, and future asset deletion can refuse "still in use" via PROTECT. The
    # serializer keeps pair and file in sync — a direct upload clears the binding, an
    # attach copies the asset's key into the FileField. NULL simply means "not a
    # library pick" (uploaded directly, or predates the library).
    image_asset = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.PROTECT,
        related_name="banners_as_image",
    )
    mobile_image_asset = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.PROTECT,
        related_name="banners_as_mobile_image",
    )
    video_asset = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.PROTECT,
        related_name="banners_as_video",
    )
    # The third text some tiles need (a section tagline, the feature paragraph).
    # Plain text like everything else here — React escapes it.
    tagline = models.CharField(max_length=300, blank=True)
    placement = models.CharField(max_length=20, choices=PLACEMENT_CHOICES, default=STRIP)
    sort = models.PositiveSmallIntegerField(default=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    # BLANK MEANS EVERYWHERE, matching `Product.available_countries`. An empty M2M reading
    # as "no markets" would make every banner invisible until somebody ticked five boxes.
    countries = models.ManyToManyField("core.Country", blank=True, related_name="banners")

    class Meta:
        ordering = ["sort", "-created_at"]

    def __str__(self) -> str:
        return f"{self.title} ({self.placement})"

    def is_live(self, now=None) -> bool:
        """Active AND inside its window. The schedule is the whole point of the model —
        a campaign that needs somebody awake at midnight to switch it on is not scheduled."""
        from django.utils import timezone

        now = now or timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and self.starts_at > now:
            return False
        if self.ends_at and self.ends_at < now:
            return False
        return True


class HomepageSection(TimeStampedModel):
    """One block on the homepage, in order.

    `config` is STRUCTURED JSON, never markup: a heading, a collection slug, a list of
    ids. That is deliberate — the storefront renders these through the same typed section
    components Plan-13 built, so a section cannot introduce HTML the sanitiser never saw.

    The storefront falls back to its own fixtures when this table is empty, so an empty
    CMS is a homepage that looks exactly as it does today rather than a blank page.
    """

    TYPE_CHOICES = [
        ("hero", "Hero"),
        ("collection_carousel", "Collection carousel"),
        ("banner_grid", "Banner grid"),
        ("editorial", "Editorial"),
        ("brand_strip", "Brand strip"),
    ]

    type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    sort = models.PositiveSmallIntegerField(default=0)
    config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self) -> str:
        return f"{self.sort}. {self.type}"


class MenuItem(TimeStampedModel):
    """A link in the header or footer.

    `cms.manage`: navigation is site structure, and the footer's policy links are exactly
    the legally load-bearing content that scope exists to protect.
    """

    HEADER = "header"
    FOOTER = "footer"
    MENU_CHOICES = [(HEADER, "Header"), (FOOTER, "Footer")]

    label = models.CharField(max_length=80)
    url = models.CharField(max_length=300)
    menu = models.CharField(max_length=10, choices=MENU_CHOICES, default=FOOTER)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    sort = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["menu", "sort", "id"]

    def __str__(self) -> str:
        return f"{self.menu}: {self.label}"


class GoogleReview(TimeStampedModel):
    """One CURATED Google review featured on the landing page.

    Curated, not synced: the Places API returns at most five "most relevant" reviews
    and no per-review permalink, so automation cannot satisfy "click goes to that
    exact review" (design ruling, 2026-08-04). A human picks the review on Google
    Maps, presses "Share review", and pastes the permalink here. That also keeps a
    mediocre rotating review off the homepage.
    """

    author = models.CharField(max_length=100)          # "Adaeze O." — as shown on Google
    location = models.CharField(max_length=100, blank=True)  # "Lagos"
    rating = models.PositiveSmallIntegerField(default=5)     # 1-5 stars
    text = models.TextField()                          # plain text; React escapes it
    review_url = models.URLField()                     # the Google share-link permalink
    reviewed_at_text = models.CharField(max_length=60, blank=True)  # "2 weeks ago", verbatim
    sort = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort", "-created_at"]

    def __str__(self) -> str:
        return f"{self.author} ({self.rating}★)"


class GoogleReviewsMeta(TimeStampedModel):
    """Singleton: the header numbers next to the featured reviews.

    Admin-entered for now ("4.8", "300+"); a Places API fetch can update it later
    without changing this shape. pk is forced to 1 so there is exactly one row.
    """

    rating = models.DecimalField(max_digits=2, decimal_places=1, default=5.0)
    review_count_text = models.CharField(max_length=40, default="")  # "300+", shown verbatim
    profile_url = models.URLField(blank=True)  # "Review us on Google" target

    class Meta:
        verbose_name_plural = "google reviews meta"

    def save(self, *args, **kwargs):
        # Forced pk=1 confuses Django's insert-or-update guess (a fresh instance with a
        # pk inserts and trips the auto created_at), so decide explicitly.
        self.pk = 1
        existing = type(self).objects.filter(pk=1).values_list("created_at", flat=True).first()
        if existing:
            self.created_at = existing
            kwargs["force_update"] = True
        else:
            kwargs["force_insert"] = True
        super().save(*args, **kwargs)
