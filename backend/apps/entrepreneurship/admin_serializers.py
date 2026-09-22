"""Admin shapes for the programme.

A READ SURFACE OVER PERSONAL DATA, built the opposite way round from an ordinary content
serializer: everything is read-only except the two fields a reviewer is actually allowed
to change (status and staff notes). A student's own words are not ours to edit — an
admin that can silently rewrite an applicant's details is an admin whose records stop
being evidence of what the applicant actually sent.
"""
from rest_framework import serializers

from apps.core.phones import format_display
from apps.entrepreneurship.models import (
    APPLICATION_STATUS_CHOICES,
    ProgramApplication,
    ProgramSettings,
)


class ProgramApplicationListSerializer(serializers.ModelSerializer):
    """One row in the applications table. PII, and no more of it than a row needs.

    `motivation` is ABSENT. It is the longest field on the model and the list would ship
    every student's paragraph in one response, which is bulk egress of exactly the kind
    `audit_reads` exists to record. It is on the detail serializer, one application at a
    time, which is how a reviewer reads it anyway.
    """

    country_name = serializers.CharField(source="country.name", read_only=True)
    country_code = serializers.CharField(source="country.code", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    phone_display = serializers.SerializerMethodField()
    has_motivation = serializers.SerializerMethodField()

    class Meta:
        model = ProgramApplication
        fields = [
            "id", "full_name", "email", "phone", "phone_display",
            "country_code", "country_name", "institution", "academic_level",
            "course_of_study", "social_handle", "has_motivation",
            "status", "status_label", "submission_count", "is_resubmission",
            "created_at",
        ]

    def get_phone_display(self, obj) -> str:
        """Formatted for a Nigerian reader, like the store cards and the careers table.
        The E.164 value rides along beside it because that is what `tel:` and `wa.me`
        links must be built from."""
        return format_display(obj.phone, viewer_country="NG")

    def get_has_motivation(self, obj) -> bool:
        return bool(obj.motivation)


class ProgramApplicationDetailSerializer(ProgramApplicationListSerializer):
    reviewed_by_name = serializers.SerializerMethodField()

    class Meta(ProgramApplicationListSerializer.Meta):
        fields = ProgramApplicationListSerializer.Meta.fields + [
            "motivation", "staff_notes", "reviewed_at", "reviewed_by_name",
        ]

    def get_reviewed_by_name(self, obj) -> str:
        user = obj.reviewed_by
        if user is None:
            return ""
        return (user.get_full_name() or "").strip() or user.email


class ProgramApplicationWriteSerializer(serializers.ModelSerializer):
    """The ONLY two things a reviewer may change.

    A whitelist rather than a blacklist: the model carries a name, an email, a phone
    number and a school, and none of them is ours to edit. If a student's details are
    wrong the answer is to ask them, not to retype their name for them.
    """

    audit_allowlist = ("status", "staff_notes")

    status = serializers.ChoiceField(choices=APPLICATION_STATUS_CHOICES, required=False)
    staff_notes = serializers.CharField(
        required=False, allow_blank=True, max_length=10000, trim_whitespace=False
    )

    class Meta:
        model = ProgramApplication
        fields = ["status", "staff_notes"]


class ProgramSettingsSerializer(serializers.ModelSerializer):
    """The intake switch. Two fields, both audited.

    WHY `closed_message` IS AUDITED TOO and not treated as cosmetic: it is the sentence
    the public sees in place of the form, so it is published copy written by one member
    of staff to strangers. The audit row is the only thing that can later say who chose
    those words.
    """

    audit_allowlist = ("is_open", "closed_message")

    class Meta:
        model = ProgramSettings
        fields = ["is_open", "closed_message", "updated_at"]
        read_only_fields = ["updated_at"]

    def validate_closed_message(self, value):
        return " ".join((value or "").split())
