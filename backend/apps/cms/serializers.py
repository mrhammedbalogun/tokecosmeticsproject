"""Public CMS serializers. Admin ones live in `admin_serializers.py`."""
from rest_framework import serializers

from apps.cms.models import Banner, HomepageSection, MenuItem, Page


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
    class Meta:
        model = Banner
        fields = [
            "id", "title", "subtitle", "image", "mobile_image",
            "cta_text", "cta_url", "placement", "sort",
        ]


class PublicHomepageSectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = HomepageSection
        fields = ["id", "type", "sort", "config"]


class PublicMenuItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuItem
        fields = ["id", "label", "url", "menu", "parent", "sort"]
