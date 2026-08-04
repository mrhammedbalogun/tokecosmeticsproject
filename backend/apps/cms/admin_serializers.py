from rest_framework import serializers

from apps.cms.models import GoogleReview, GoogleReviewsMeta, Banner, HomepageSection, MenuItem, Page


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


class BannerAdminSerializer(serializers.ModelSerializer):
    """Every field a campaign depends on is audited: a banner that appeared or vanished at
    the wrong moment is a marketing incident somebody will want explained."""

    audit_allowlist = (
        "title", "subtitle", "cta_text", "cta_url", "video_url", "placement", "sort",
        "starts_at", "ends_at", "is_active", "countries",
    )

    is_live = serializers.BooleanField(read_only=True)

    class Meta:
        model = Banner
        fields = [
            "id", "title", "subtitle", "image", "mobile_image", "cta_text", "cta_url",
            "video_url", "placement", "sort", "starts_at", "ends_at", "is_active",
            "countries", "is_live", "updated_at",
        ]

    def validate(self, attrs):
        starts = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts and ends and starts >= ends:
            raise serializers.ValidationError(
                {"ends_at": "The end must come after the start, or the banner never shows."}
            )
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
