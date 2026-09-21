"""Admin shapes for the careers board.

TWO FAMILIES, TWO AUDIENCES. The posting serializers are an ordinary content write
surface. The application serializers are a READ surface over personal data, and they are
built the other way round on purpose: everything is read-only except the three fields a
reviewer is actually allowed to change (status, staff notes, and — implicitly — who
reviewed it). A candidate's own words are not editable by us.

THE RESUME KEY IS NEVER SERIALISED. Not to the admin either. It is an S3 object path,
the admin has no use for it, and a key that reaches a browser is a key that reaches a
browser's history, a screenshot and a support ticket. The download endpoint takes an
application id and resolves the key server-side.
"""
from django.utils import timezone
from rest_framework import serializers

from apps.careers.models import (
    APPLICATION_STATUS_CHOICES,
    JobApplication,
    JobLocation,
    JobPosting,
    STATUS_OPEN,
)
from apps.core.models import Country
from apps.core.phones import format_display


class JobLocationAdminSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = JobLocation
        fields = ["id", "label", "sort_order"]

    def validate_label(self, value):
        label = " ".join((value or "").split())
        if not label:
            raise serializers.ValidationError("Give the location a name.")
        return label


class JobPostingAdminSerializer(serializers.ModelSerializer):
    """One posting and all its locations, written in one request.

    NESTED WRITES, deliberately, rather than a separate `/locations/` endpoint. The
    eleven Sales Representative cities are the whole reason this model exists; making an
    operator add them one HTTP call at a time would mean a half-saved posting is a normal
    state, and "I added Enugu but the save failed" would be a real support email. One
    request, one transaction, all eleven or none.
    """

    audit_allowlist = (
        "title", "slug", "department", "employment_type", "workplace_type", "country",
        "compensation_text", "summary", "description", "requirements", "status",
        "closes_at", "sort_order", "locations",
    )

    locations = JobLocationAdminSerializer(many=True, required=False)
    country = serializers.PrimaryKeyRelatedField(
        # "ZZ / International" is a pricing bucket, not a place anybody is hired into.
        queryset=Country.objects.filter(is_rest_of_world=False),
    )
    country_name = serializers.CharField(source="country.name", read_only=True)
    employment_type_label = serializers.CharField(
        source="get_employment_type_display", read_only=True
    )
    workplace_type_label = serializers.CharField(
        source="get_workplace_type_display", read_only=True
    )
    is_accepting = serializers.BooleanField(read_only=True)
    is_archived = serializers.BooleanField(read_only=True)
    # Annotated by the viewset. Named `application_count` and not `applications` so it can
    # never be mistaken for the list of them — this serializer must not grow a path to
    # candidate data, since it sits behind `careers.manage` and not the PII scope.
    application_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = JobPosting
        fields = [
            "id", "title", "slug", "department", "employment_type",
            "employment_type_label", "workplace_type", "workplace_type_label",
            "country", "country_name", "compensation_text", "summary", "description",
            "requirements", "status", "closes_at", "sort_order", "locations",
            "published_at", "archived_at", "is_accepting", "is_archived",
            "application_count", "created_at", "updated_at",
        ]
        read_only_fields = ["published_at", "archived_at", "created_at", "updated_at"]
        extra_kwargs = {
            # Blank on create means "mint one from the title" (`JobPosting.save`). Sent
            # with a value it is honoured, because a slug is a published URL and an
            # operator re-publishing an old advert may need the old link to keep working.
            "slug": {"required": False, "allow_blank": True},
        }

    def validate_title(self, value):
        title = " ".join((value or "").split())
        if len(title) < 2:
            raise serializers.ValidationError("Give the role a title.")
        return title

    def validate_closes_at(self, value):
        """A deadline in the past closes the role the moment it is saved.

        Refused rather than accepted, because the only way to type one is by mistake and
        the symptom — a role that publishes and immediately stops taking applications —
        reads as a broken feature rather than as a typo.
        """
        if value is not None and value <= timezone.now():
            raise serializers.ValidationError("That closing date has already passed.")
        return value

    def validate(self, attrs):
        """An OPEN posting must be worth landing on.

        Checked here and not in `save()` because it is a publishing rule, not a data
        invariant: a draft is allowed to be half-written, which is what a draft is for.
        The moment it goes public it owes the reader a description.
        """
        status = attrs.get("status", getattr(self.instance, "status", None))
        if status == STATUS_OPEN:
            description = attrs.get(
                "description", getattr(self.instance, "description", "")
            )
            if not (description or "").strip():
                raise serializers.ValidationError(
                    {"description": ["Write the role description before opening it."]}
                )
        return attrs

    def create(self, validated_data):
        locations = validated_data.pop("locations", [])
        posting = JobPosting.objects.create(**validated_data)
        self._sync_locations(posting, locations)
        return posting

    def update(self, instance, validated_data):
        locations = validated_data.pop("locations", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if locations is not None:
            self._sync_locations(instance, locations)
        return instance

    def _sync_locations(self, posting: JobPosting, rows: list[dict]) -> None:
        """Make the stored locations match what was sent, by id where one was given.

        UPDATE-IN-PLACE FOR KNOWN IDS, and it is load-bearing: `JobApplication.location`
        points at these rows, and delete-then-recreate would null every applicant's
        chosen city on every edit of the posting. Rows that genuinely disappear are
        deleted, which `SET_NULL` absorbs — the application keeps its `location_label`
        snapshot, so the screen still says where they applied.
        """
        existing = {row.pk: row for row in posting.locations.all()}
        keep: set[int] = set()
        for index, row in enumerate(rows):
            pk = row.get("id")
            label = row["label"]
            order = row.get("sort_order", index)
            current = existing.get(pk) if pk else None
            if current is not None:
                current.label = label
                current.sort_order = order
                current.save(update_fields=["label", "sort_order", "updated_at"])
                keep.add(current.pk)
            else:
                created = JobLocation.objects.create(
                    job=posting, label=label, sort_order=order
                )
                keep.add(created.pk)
        for pk, row in existing.items():
            if pk not in keep:
                row.delete()

    def validate_locations(self, value):
        labels = [" ".join((row.get("label") or "").split()).lower() for row in value]
        if len(labels) != len(set(labels)):
            raise serializers.ValidationError(
                "Two locations on this role have the same name."
            )
        return value


class JobApplicationListSerializer(serializers.ModelSerializer):
    """One row in the applications table. PII, and no more of it than a row needs.

    The cover letter is absent: it is the longest field on the model and the list would
    ship every candidate's in one response, which is bulk egress of the exact kind
    `audit_reads` exists to record. It is on the detail serializer, one application at a
    time, which is how a reviewer reads it anyway.
    """

    job_slug = serializers.CharField(source="job.slug", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    phone_display = serializers.SerializerMethodField()
    has_cover_letter = serializers.SerializerMethodField()

    class Meta:
        model = JobApplication
        fields = [
            "id", "job", "job_slug", "job_title", "location_label", "full_name",
            "email", "phone", "phone_display", "status", "status_label",
            "has_cover_letter", "resume_original_name", "resume_size",
            "submission_count", "is_resubmission", "created_at",
        ]

    def get_phone_display(self, obj) -> str:
        """Formatted for a Nigerian reader, like the store cards. The E.164 value rides
        along beside it because that is what `tel:` and `wa.me` links must be built from."""
        return format_display(obj.phone, viewer_country="NG")

    def get_has_cover_letter(self, obj) -> bool:
        return bool(obj.cover_letter)


class JobApplicationDetailSerializer(JobApplicationListSerializer):
    reviewed_by_name = serializers.SerializerMethodField()

    class Meta(JobApplicationListSerializer.Meta):
        fields = JobApplicationListSerializer.Meta.fields + [
            "cover_letter", "staff_notes", "reviewed_at", "reviewed_by_name",
            "resume_content_type",
        ]

    def get_reviewed_by_name(self, obj) -> str:
        user = obj.reviewed_by
        if user is None:
            return ""
        return (user.get_full_name() or "").strip() or user.email


class JobApplicationWriteSerializer(serializers.ModelSerializer):
    """The ONLY two things a reviewer may change.

    A whitelist rather than a blacklist: the model carries a name, an email, a phone
    number and a CV key, and none of them is ours to edit. If a candidate's details are
    wrong, the answer is to ask them, not to retype their name for them — an admin that
    can silently rewrite an applicant's contact details is an admin whose records stop
    being evidence of what the candidate actually sent.
    """

    audit_allowlist = ("status", "staff_notes")

    status = serializers.ChoiceField(choices=APPLICATION_STATUS_CHOICES, required=False)
    staff_notes = serializers.CharField(
        required=False, allow_blank=True, max_length=10000, trim_whitespace=False
    )

    class Meta:
        model = JobApplication
        fields = ["status", "staff_notes"]
