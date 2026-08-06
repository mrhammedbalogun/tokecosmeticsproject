from rest_framework import serializers

from apps.reviews.models import Review


class ReviewAdminSerializer(serializers.ModelSerializer):
    """Row for the admin Reviews screen. Only `status` is writable — the words belong
    to the customer; staff hide or delete a review, they never edit one."""

    audit_allowlist = ("status",)

    product_name = serializers.CharField(source="product.name", read_only=True)
    product_slug = serializers.CharField(source="product.slug", read_only=True)
    author_email = serializers.EmailField(source="user.email", read_only=True)
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            "id", "product_name", "product_slug", "author_name", "author_email",
            "rating", "title", "body", "status", "created_at",
        ]
        read_only_fields = ["id", "rating", "title", "body", "created_at"]

    def get_author_name(self, obj):
        name = f"{obj.user.first_name} {obj.user.last_name}".strip()
        return name or obj.user.email
