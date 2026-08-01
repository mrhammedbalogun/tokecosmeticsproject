from rest_framework import serializers

from apps.cms.models import Banner, HomepageSection, MenuItem, Page


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
        "title", "subtitle", "cta_text", "cta_url", "placement", "sort",
        "starts_at", "ends_at", "is_active", "countries",
    )

    is_live = serializers.BooleanField(read_only=True)

    class Meta:
        model = Banner
        fields = [
            "id", "title", "subtitle", "image", "mobile_image", "cta_text", "cta_url",
            "placement", "sort", "starts_at", "ends_at", "is_active", "countries",
            "is_live", "updated_at",
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
