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
    # The model's TextField is unbounded; cap accepted input here so a review can't
    # arrive at request-body scale (title is already capped at 140 by the model).
    body = serializers.CharField(max_length=4000)

    class Meta:
        model = Review
        fields = ["rating", "title", "body"]

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value
