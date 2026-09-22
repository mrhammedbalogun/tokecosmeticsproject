"""What the public may see and send. Every field named explicitly.

READ SERIALIZERS ARE ALLOWLISTS, not `fields = "__all__"`. These sit on unauthenticated
endpoints and the model beside them carries `staff_notes`, a reviewer's identity and a
stranger's phone number. A future column must be added here deliberately to become
public — the same rule `apps.stores.serializers` and `apps.careers.serializers` state,
and for the same reason.
"""
from rest_framework import serializers

from apps.core.models import Country
from apps.core.phones import normalize_e164
from apps.entrepreneurship.models import ProgramSettings

MOTIVATION_MAX = 2000


class ProgramCountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ["code", "name"]


class ProgramConfigSerializer(serializers.Serializer):
    """The two things the page cannot hardcode: whether it is taking applications, and
    which markets the dropdown offers.

    THE COUNTRY LIST IS SERVED RATHER THAN HARDCODED even though it has changed once in
    the life of this shop. The reason is the failure mode, not the churn: a hardcoded
    list that falls behind renders a dropdown whose value the API then refuses, and the
    student sees "select a valid choice" on a country they can see in the box. One
    source, one answer.
    """

    is_open = serializers.BooleanField(read_only=True)
    # The sentence to show INSTEAD of the form. Always sent, even while open — a client
    # that caches this response and later finds `is_open` false still has the words.
    closed_message = serializers.CharField(read_only=True)
    countries = ProgramCountrySerializer(many=True, read_only=True)

    @staticmethod
    def build() -> dict:
        row = ProgramSettings.load()
        return {
            "is_open": row.is_open,
            "closed_message": row.public_closed_message,
            "countries": list(
                # "ZZ / International" is a pricing bucket, not a country anybody studies
                # in — the same exclusion `careers.admin_serializers` makes.
                Country.objects.filter(is_active=True, is_rest_of_world=False)
                .order_by("-is_default", "name")
                .values("code", "name")
            ),
        }


class ApplicationCreateSerializer(serializers.Serializer):
    """An application, as it arrives.

    Deliberately a plain `Serializer` and not a `ModelSerializer`: the row that gets
    written carries a status, a reviewer and a submission count that no client may ever
    set, and a ModelSerializer over this model would have to exclude more fields than it
    includes.
    """

    country = serializers.SlugRelatedField(
        slug_field="code",
        queryset=Country.objects.filter(is_active=True, is_rest_of_world=False),
        error_messages={
            # DRF's default is "Object with code=XX does not exist", which is a sentence
            # about our database written at a student.
            "does_not_exist": "Choose the country you are studying in.",
            "invalid": "Choose the country you are studying in.",
        },
    )
    full_name = serializers.CharField(max_length=120)
    email = serializers.EmailField(max_length=254)
    phone = serializers.CharField(max_length=32)
    institution = serializers.CharField(max_length=160)
    academic_level = serializers.CharField(max_length=60)
    course_of_study = serializers.CharField(max_length=120)
    social_handle = serializers.CharField(
        max_length=120, required=False, allow_blank=True, trim_whitespace=True
    )
    motivation = serializers.CharField(
        max_length=MOTIVATION_MAX, required=False, allow_blank=True, trim_whitespace=True
    )
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

        The error text comes from `normalize_e164` unchanged — it is written to be read
        by the person typing, and re-wording it here would create a second sentence for
        one rule.
        """
        try:
            phone = normalize_e164(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from None
        if not phone:
            raise serializers.ValidationError("Enter a phone number we can reach you on.")
        return phone

    def validate_institution(self, value):
        name = " ".join((value or "").split())
        if len(name) < 2:
            raise serializers.ValidationError(
                "Tell us where you study — the full name of your school."
            )
        return name

    def validate_academic_level(self, value):
        level = " ".join((value or "").split())
        if not level:
            raise serializers.ValidationError("Tell us what level you are in.")
        return level

    def validate_course_of_study(self, value):
        course = " ".join((value or "").split())
        if not course:
            raise serializers.ValidationError("Tell us what you are studying.")
        return course

    def validate_social_handle(self, value):
        """Collapsed whitespace only. NOT validated as a URL or a handle.

        A student may type `@ada.sells`, `instagram.com/ada.sells`, `Ada on TikTok`, or
        two of those. Every rule that would refuse one of them refuses a real answer on
        an OPTIONAL field, which is the worst trade on a form: it costs a submission to
        gain nothing, since a reviewer reads this with their eyes either way.
        """
        return " ".join((value or "").split())[:120]


class ApplicationResultSerializer(serializers.Serializer):
    """What the applicant gets back. Almost nothing, on purpose.

    No id, no status, no indication of whether this replaced an earlier application —
    every successful submission must look identical, or the response itself becomes the
    enumeration oracle that `services` refuses to be.
    """

    full_name = serializers.CharField(read_only=True)
