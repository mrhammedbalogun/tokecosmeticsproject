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
        # /affiliates (2026-08-16). The referral page is the first NON-homepage surface to
        # take banner artwork, which is safe because `PublicHomepageView` already serves
        # every live banner regardless of placement — the endpoint is named for its first
        # consumer, not its contents. Both slots are OPTIONAL by design: with no banner
        # the page drops the band entirely rather than rendering an empty coloured
        # rectangle, so it reads as finished either way (see the storefront page's note).
        ("affiliate_hero", "Affiliates page — hero image"),
        ("affiliate_tier", "Affiliates page — ₦200k Club image"),
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
    # 2026-08-09. Until now playback was hardcoded to autoplay+loop in the storefront,
    # so a long film could not be offered without every visitor downloading it. LOOP is
    # the default because it is what every existing banner already does — the migration
    # must not change how the live homepage behaves.
    LOOP = "loop"
    CLICK = "click"
    VIDEO_MODE_CHOICES = [(LOOP, "Loop silently"), (CLICK, "Play on click")]
    video_mode = models.CharField(max_length=5, choices=VIDEO_MODE_CHOICES, default=LOOP)
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

    ── WHY STILL CURATED (re-examined 2026-08-17, ruling UPHELD on new grounds) ──────
    The 2026-08-04 ruling rested on two premises. One of them has since died:

    * DEAD: "the Places API has no per-review permalink." Places API (New) now returns
      `googleMapsUri` on every review object — verified against the live listing on
      2026-08-17. Automation *could* satisfy "click goes to that exact review".
    * ALIVE, and now load-bearing on its own: **Google forbids storing this content.**
      Maps Platform Service Specific Terms §14.3 allows caching exactly one thing from
      the Places API — "latitude and longitude values... for up to 30 consecutive
      calendar days" — and §A.3 allows Google IDs. Review text, author names and
      avatars have NO storage allowance at all. Persisting an API-pulled review in
      this table would be off-terms no matter how often it is refreshed.
    * ALIVE: five relevance-picked reviews is all the Places API ever returns. All
      five are currently featured, in Google's own order — showing everything means
      nothing is filtered, so the policies' "describe how reviews are ordered and
      filtered" disclosure has nothing to disclose. Note four of the five are two
      years old, which is why `reviewed_at_text` is left blank on them.

    So these rows hold reviews a HUMAN chose and transcribed from the public listing,
    testimonial-style, each linking back to its source — content this table is free to
    keep. Do not "upgrade" this to a Places sync; that path was costed and rejected.
    The sanctioned route to real automation is the **Google Business Profile API**
    (owner OAuth, all reviews not five, free, no per-call billing), which needs an
    access application. See `docs/runbooks/google-apis-setup.md`.
    """

    author = models.CharField(max_length=100)          # "Adaeze O." — as shown on Google
    location = models.CharField(max_length=100, blank=True)  # "Lagos"
    rating = models.PositiveSmallIntegerField(default=5)     # 1-5 stars
    text = models.TextField()                          # plain text; React escapes it
    # 500, not the 200 default: a review's googleMapsUri permalink is ~175 chars of
    # base64 protobuf and Google documents no ceiling for it.
    review_url = models.URLField(max_length=500)       # the review's own permalink
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


class TrainingResource(TimeStampedModel):
    """One training video in the staff library (2026-08-23).

    THE LIBRARY IS FOR STAFF, NOT CUSTOMERS. Nothing in `apps/cms/urls.py` (the
    public CMS surface) may ever serve these rows: the descriptions are internal
    process notes and the videos may be unlisted on YouTube, which is privacy by
    obscurity that survives only as long as the links stay inside the admin.

    THE SOURCE OF TRUTH IS `video_id`, derived by `save()` from `youtube_url` via
    `apps/cms/youtube.py` — the same arrangement as `StoreLocation`'s name/address
    keys, and for the same reason: the derived value is what the unique constraint
    and the admin's player/thumbnail URLs are built from, so it must exist on every
    row however the row was created. The serializer validates the URL FIRST and puts
    a sentence under the field; `save()` re-deriving is what keeps a shell-created
    row honest. `bulk_create` bypasses `save()` and must set `video_id` itself.

    `is_published` instead of delete-to-hide: the Owner drafts a training, watches
    it back, then flips it on — and can pull one that went stale without losing the
    title and description typed for it. Staff (`TrainingLibraryView`) only ever see
    published rows. DELETE is a real delete, unlike stores: a row here is a link
    plus two typed fields, the video itself lives on YouTube, and the scope that can
    delete (`training.manage`) is the Owner's alone.

    `position` orders the curriculum ("watch these in order"). Default 0 for every
    row means untouched rows fall back to insertion order via the `id` tie-break.
    """

    title = models.CharField(max_length=200)
    # Plain text, rendered with newlines preserved — never HTML. The admin is the
    # only renderer and it must never `dangerouslySetInnerHTML` staff-typed prose.
    description = models.TextField(blank=True)
    # The canonical `watch?v=` spelling, rewritten by the serializer from whatever
    # was pasted. Kept (rather than only the id) so "open on YouTube" needs no
    # reconstruction and the row is legible in the Django admin and in audit rows.
    youtube_url = models.URLField(max_length=200)
    video_id = models.CharField(max_length=16, editable=False, db_index=True)
    position = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            # One row per video. Two trainings pointing at the same video is an
            # accidental re-add in every real case; the serializer refuses it with a
            # sentence naming the existing row, and this is the backstop for the
            # race and for non-serializer writes.
            models.UniqueConstraint(fields=["video_id"], name="training_unique_video"),
        ]

    def __str__(self) -> str:
        state = "published" if self.is_published else "hidden"
        return f"{self.title} ({state})"

    def save(self, *args, **kwargs):
        from apps.cms.youtube import parse_youtube_video_id

        derived = parse_youtube_video_id(self.youtube_url)
        if derived:
            self.video_id = derived
        return super().save(*args, **kwargs)
