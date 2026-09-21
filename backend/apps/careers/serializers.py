"""What the public may see and send. Every field named explicitly.

READ SERIALIZERS ARE ALLOWLISTS, not `fields = "__all__"`. These sit on
unauthenticated endpoints and the models beside them carry `staff_notes`, an S3 key and
a stranger's phone number. A future column must be added here deliberately to become
public — the same rule `apps.stores.serializers` states and for the same reason.
"""
from rest_framework import serializers

from apps.careers.models import JobApplication, JobLocation, JobPosting
from apps.careers.resume_storage import MAX_RESUME_BYTES
from apps.core.phones import normalize_e164


class JobLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobLocation
        fields = ["id", "label"]


class JobPostingSerializer(serializers.ModelSerializer):
    """One role, as a card and as a page. The same shape serves both.

    Two shapes would mean two chances for the listing and the detail page to disagree
    about whether a role is still taking applications, and the listing is where somebody
    decides whether to spend twenty minutes on a cover letter.
    """

    employment_type_label = serializers.CharField(
        source="get_employment_type_display", read_only=True
    )
    workplace_type_label = serializers.CharField(
        source="get_workplace_type_display", read_only=True
    )
    locations = JobLocationSerializer(many=True, read_only=True)
    country_name = serializers.CharField(source="country.name", read_only=True)
    country_code = serializers.CharField(source="country.code", read_only=True)
    # Computed on the server, never re-derived in the browser: `closes_at` makes a role
    # stop accepting applications without anybody editing it, and a client clock is not
    # something to hang that on.
    is_accepting = serializers.BooleanField(read_only=True)

    class Meta:
        model = JobPosting
        fields = [
            "slug",
            "title",
            "department",
            "employment_type",
            "employment_type_label",
            "workplace_type",
            "workplace_type_label",
            "country_name",
            "country_code",
            "compensation_text",
            "summary",
            "description",
            "requirements",
            "locations",
            "status",
            "is_accepting",
            "published_at",
            "closes_at",
        ]
        # `id` is absent deliberately. The URL vocabulary for this feature is slugs, and a
        # careers board gives a stranger no reason to learn our primary keys.


class UploadTicketRequestSerializer(serializers.Serializer):
    """The one thing a client sends to get an upload ticket: what they called the file.

    The name is used for exactly two things — choosing the extension (validated against
    an allow-list before it can reach a key) and being shown back to a reviewer. It is
    never joined onto a path, and the key the ticket pins is minted here, not sent.
    """

    filename = serializers.CharField(max_length=255)
    # Optional and advisory: it lets the endpoint refuse an obviously oversized file
    # before minting a ticket for it. The REAL cap is the presigned policy and the HEAD
    # at finalize; this only saves a round trip.
    size = serializers.IntegerField(required=False, min_value=0)

    def validate_size(self, value):
        if value > MAX_RESUME_BYTES:
            raise serializers.ValidationError("That file is larger than 5MB. Attach a smaller CV.")
        return value


class ApplicationCreateSerializer(serializers.Serializer):
    """An application, as it arrives. Plain JSON — the file is already in the bucket.

    Deliberately a plain `Serializer` and not a `ModelSerializer`: the row that gets
    written carries snapshots and an S3 key that no client may ever set, and a
    ModelSerializer over this model would have to exclude more fields than it includes.
    """

    full_name = serializers.CharField(max_length=120)
    email = serializers.EmailField(max_length=254)
    phone = serializers.CharField(max_length=32)
    cover_letter = serializers.CharField(
        max_length=5000, required=False, allow_blank=True, trim_whitespace=True
    )
    location = serializers.IntegerField(required=False, allow_null=True)
    # The server-minted key from the upload ticket, and the name to show a reviewer.
    upload_key = serializers.CharField(max_length=255)
    resume_filename = serializers.CharField(max_length=255)
    # The honeypot. A field no human sees and no real browser fills; see the view.
    website = serializers.CharField(required=False, allow_blank=True)
    turnstile_token = serializers.CharField(required=False, allow_blank=True)

    def validate_full_name(self, value):
        name = " ".join((value or "").split())
        if len(name) < 2:
            raise serializers.ValidationError("Enter your full name.")
        return name

    def validate_phone(self, value):
        """Strict E.164, the same rule every other stored number in this platform obeys.

        The error text comes from `normalize_e164` unchanged — it is written to be read by
        the person typing, and re-wording it here would create a second sentence for one
        rule.
        """
        try:
            phone = normalize_e164(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from None
        if not phone:
            raise serializers.ValidationError("Enter a phone number we can reach you on.")
        return phone


class ApplicationResultSerializer(serializers.ModelSerializer):
    """What the applicant gets back. Almost nothing, on purpose.

    No id, no status, no indication of whether this replaced an earlier application —
    every successful submission must look identical, or the response itself becomes the
    enumeration oracle the 409 was rejected for being.
    """

    class Meta:
        model = JobApplication
        fields = ["job_title"]
