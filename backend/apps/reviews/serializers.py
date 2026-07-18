from rest_framework import serializers

from apps.reviews.models import Review


class ReviewReadSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ["rating", "title", "body", "author", "created_at"]

    def get_author(self, obj):
        # Public display name only — never the email.
        name = obj.user.first_name or "Verified buyer"
        return name


class ReviewWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["rating", "title", "body"]

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value
