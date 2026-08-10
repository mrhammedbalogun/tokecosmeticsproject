from PIL import Image
from rest_framework import serializers

from apps.cms.models import (
    GoogleReview, GoogleReviewsMeta, Banner, HomepageSection, MediaAsset, MenuItem, Page,
)

# Server-side upload ceilings (2026-08-07). Until now the only size check lived in the
# admin's Next action layer, which a direct API client never passes through — these are
# the caps that actually hold. Values match what the surfaces need: no homepage image
# should be anywhere near 15MB, and 80MB mirrors the long-standing video guidance.
MAX_IMAGE_BYTES = 15 * 1024 * 1024
# 128MB since 2026-08-09. The presigned path reads this for its S3 policy condition and
# again when re-checking what actually landed; the legacy multipart path still reads it
# too. ONE constant — a second copy is how `next.config.ts`'s unreachable 85MB ended up
# looking authoritative.
MAX_VIDEO_BYTES = 128 * 1024 * 1024
VIDEO_EXTENSIONS = (".mp4", ".webm")


def sniff_kind(file) -> str:
    """image | video, decided by the bytes and the extension — never the client's
    Content-Type, which is whatever the caller typed. Pillow-verifiable → image (the
    same bar `ImageField` sets); .mp4/.webm otherwise → video; anything else raises."""
    try:
        with Image.open(file) as probe:
            probe.verify()
        file.seek(0)
        return MediaAsset.IMAGE
    # Broad on purpose: UnidentifiedImageError is "not an image", but a truncated file
    # or a decompression bomb raises other things, and every one of them means the same
    # here — "do not treat these bytes as an image".
    except Exception:
        file.seek(0)
    if str(file.name or "").lower().endswith(VIDEO_EXTENSIONS):
        return MediaAsset.VIDEO
    raise serializers.ValidationError(
        "That file is neither an image nor an mp4/webm video."
    )


class PageAdminSerializer(serializers.ModelSerializer):
    """`body_source` is the writable field; `body` is derived on save and read-only.

    The audit allow-list deliberately omits both: a page body is prose, often long, and
    `MAX_CHANGES_BYTES` would truncate the row into a `__keys__` stub anyway. What matters
    for the record is WHICH page changed, its status and its URL — the body itself is
    recoverable from the page, which is not deletable.
    """

    audit_allowlist = ("title", "slug", "status", "seo_title", "seo_description", "sort")

    body = serializers.CharField(read_only=True)

    class Meta:
        model = Page
        fields = [
            "id", "title", "slug", "body_source", "body", "status",
            "seo_title", "seo_description", "sort", "updated_at",
        ]


class MediaAssetAdminSerializer(serializers.ModelSerializer):
    """The library. Upload once, attach anywhere — see `MediaAsset`'s docstring.

    `kind`, `original_name` and `size` are all derived from the file on create, never
    submitted: the client's word on what a file is decides nothing. The allowlist's
    `file` entry audits as the uploaded filename (`audit._jsonable` stringifies an
    `UploadedFile`), which is exactly the useful, bounded fact."""

    audit_allowlist = ("file",)

    class Meta:
        model = MediaAsset
        fields = ["id", "file", "kind", "original_name", "size", "created_at"]
        read_only_fields = ["kind", "original_name", "size", "created_at"]

    def validate_file(self, file):
        kind = sniff_kind(file)
        limit = MAX_IMAGE_BYTES if kind == MediaAsset.IMAGE else MAX_VIDEO_BYTES
        if file.size > limit:
            raise serializers.ValidationError(
                f"Keep {kind}s under {limit // (1024 * 1024)} MB — compress the file first."
            )
        self._sniffed_kind = kind
        return file

    def create(self, validated_data):
        file = validated_data["file"]
        request = self.context.get("request")
        return MediaAsset.objects.create(
            file=file,
            kind=self._sniffed_kind,
            original_name=str(file.name or "")[:255],
            size=file.size,
            uploaded_by=getattr(request, "user", None) if request else None,
        )


class BannerAdminSerializer(serializers.ModelSerializer):
    """Every field a campaign depends on is audited: a banner that appeared or vanished at
    the wrong moment is a marketing incident somebody will want explained. That includes
    the ARTWORK since 2026-08-07 — the file fields audit as filenames, the `_asset`
    fields as library ids (they are readable fields, which the audit guard's write-only
    seatbelt requires)."""

    audit_allowlist = (
        "title", "subtitle", "tagline", "cta_text", "cta_url", "placement", "sort",
        "starts_at", "ends_at", "is_active", "countries",
        "image", "mobile_image", "video", "video_mode",
        "image_asset", "mobile_image_asset", "video_asset",
    )

    # Media slot ←→ library binding, kept in sync both ways in validate().
    ASSET_SYNC = {
        "image_asset": "image",
        "mobile_image_asset": "mobile_image",
        "video_asset": "video",
    }

    is_live = serializers.BooleanField(read_only=True)

    class Meta:
        model = Banner
        fields = [
            "id", "title", "subtitle", "tagline", "image", "mobile_image", "video",
            "video_mode", "cta_text",
            "cta_url", "placement", "sort", "starts_at", "ends_at", "is_active",
            "countries", "is_live", "updated_at",
            "image_asset", "mobile_image_asset", "video_asset",
        ]
        # `null` is how the admin says "remove this file" (clearBannerMediaAction), and
        # DRF file fields refuse null unless told otherwise — without this the Remove
        # buttons 400 with "This field may not be null." validate() maps the null to ""
        # before it reaches the model, whose file columns are NOT NULL varchars.
        extra_kwargs = {
            "image": {"allow_null": True},
            "mobile_image": {"allow_null": True},
            "video": {"allow_null": True},
        }

    def validate_image(self, file):
        return self._checked_upload(file, "image")

    def validate_mobile_image(self, file):
        return self._checked_upload(file, "mobile image")

    def validate_video(self, file):
        if file and file.size > MAX_VIDEO_BYTES:
            raise serializers.ValidationError("Keep videos under 80 MB — compress the file first.")
        return file

    @staticmethod
    def _checked_upload(file, noun):
        # Clearing sends null; only real uploads get the cap. ImageField already ran
        # Pillow, so only size is left to check here.
        if file and file.size > MAX_IMAGE_BYTES:
            raise serializers.ValidationError(f"Keep {noun}s under 15 MB — compress the file first.")
        return file

    def validate(self, attrs):
        starts = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts and ends and starts >= ends:
            raise serializers.ValidationError(
                {"ends_at": "The end must come after the start, or the banner never shows."}
            )
        # ── Library binding ↔ file sync ────────────────────────────────────────────
        # One slot, two writable spellings: a direct upload (`image`) or a library pick
        # (`image_asset`). Whichever arrives rewrites the other, so the pair can never
        # drift — a stale binding would misreport "where did this artwork come from"
        # and, worse, PROTECT would block deleting an asset the banner stopped showing.
        for asset_field, file_field in self.ASSET_SYNC.items():
            if asset_field in attrs and file_field in attrs:
                raise serializers.ValidationError(
                    {asset_field: "Send an upload or a library pick, not both."}
                )
            if asset_field in attrs:
                asset = attrs[asset_field]
                if asset is None:
                    # Unbinding removes the artwork too — "detach but keep showing the
                    # file" is a state the admin has no way to display or undo.
                    attrs[file_field] = None
                else:
                    expected = MediaAsset.VIDEO if file_field == "video" else MediaAsset.IMAGE
                    if asset.kind != expected:
                        raise serializers.ValidationError(
                            {asset_field: f"That library file is a {asset.kind}, not a {expected}."}
                        )
                    # A string assigns the KEY — the two rows share one S3 object, no
                    # copy, no re-upload. Safe because nothing ever deletes the object.
                    attrs[file_field] = asset.file.name
            elif file_field in attrs:
                attrs[asset_field] = None
            # "" rather than None for a cleared file — the model columns are NOT NULL.
            if file_field in attrs and attrs[file_field] is None:
                attrs[file_field] = ""
        return attrs


class HomepageSectionAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = ("type", "sort", "config", "is_active")

    class Meta:
        model = HomepageSection
        fields = ["id", "type", "sort", "config", "is_active", "updated_at"]


class MenuItemAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = ("label", "url", "menu", "parent", "sort", "is_active")

    class Meta:
        model = MenuItem
        fields = ["id", "label", "url", "menu", "parent", "sort", "is_active"]


class GoogleReviewAdminSerializer(serializers.ModelSerializer):
    """Everything is audited: a fabricated five-star review on the homepage is a
    reputational incident, and the trail must say who put it there."""

    audit_allowlist = ("author", "location", "rating", "text", "review_url",
                       "reviewed_at_text", "sort", "is_active")

    class Meta:
        model = GoogleReview
        fields = ["id", "author", "location", "rating", "text", "review_url",
                  "reviewed_at_text", "sort", "is_active", "updated_at"]

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Stars run 1 to 5.")
        return value

    def validate_review_url(self, value):
        # The whole point of curation is the permalink. A non-Google URL is almost
        # certainly a paste mistake, and the card would send customers somewhere odd.
        if "google" not in value and "g.co" not in value and "goo.gl" not in value:
            raise serializers.ValidationError(
                "Paste the review's Google share-link (Share review → Copy link)."
            )
        return value


class GoogleReviewsMetaAdminSerializer(serializers.ModelSerializer):
    audit_allowlist = ("rating", "review_count_text", "profile_url")

    class Meta:
        model = GoogleReviewsMeta
        fields = ["rating", "review_count_text", "profile_url", "updated_at"]
