"""Public CMS serializers. Admin ones live in `admin_serializers.py`."""
from rest_framework import serializers

from apps.cms.models import Banner, GoogleReview, HomepageSection, MenuItem, Page


class PublicPageSerializer(serializers.ModelSerializer):
    """What the storefront renders.

    `body` (sanitised) is exposed and `body_source` (raw) is NOT: the unsanitised
    submission never leaves the admin surface, so no public client can be tricked into
    rendering it.
    """

    class Meta:
        model = Page
        fields = ["title", "slug", "body", "seo_title", "seo_description", "updated_at"]


class PublicBannerSerializer(serializers.ModelSerializer):
    # The wire name stays `video_url` (the storefront renders it); the source is now
    # the uploaded file's S3 URL.
    video_url = serializers.SerializerMethodField()

    class Meta:
        model = Banner
        fields = [
            "id", "title", "subtitle", "image", "mobile_image",
            "cta_text", "cta_url", "video_url", "placement", "sort",
        ]

    def get_video_url(self, banner) -> str:
        if not banner.video:
            return ""
        url = banner.video.url
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request and url.startswith("/") else url


class PublicHomepageSectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = HomepageSection
        fields = ["id", "type", "sort", "config"]


class PublicMenuItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuItem
        fields = ["id", "label", "url", "menu", "parent", "sort"]


class PublicGoogleReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoogleReview
        fields = ["id", "author", "location", "rating", "text", "review_url",
                  "reviewed_at_text", "sort"]
