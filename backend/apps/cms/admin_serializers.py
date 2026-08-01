from rest_framework import serializers

from apps.cms.models import Page


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
