"""Test helpers for the programme. Kept out of `tests/` so an admin shell and a future
management command can use them too, matching `apps.careers.factories`."""
from apps.core.models import Country
from apps.entrepreneurship.models import ProgramApplication


def application(
    email="chidinma@example.com",
    *,
    full_name="Chidinma Eze",
    status="new",
    **overrides,
):
    """One application, `new` by default.

    NEW by default because the interesting tests are about the de-duplication rule, and
    a decided row is a deliberate `status="approved"` — which reads at the call site as
    the exception it is.
    """
    country = overrides.pop("country", None) or Country.objects.get(code="NG")
    return ProgramApplication.objects.create(
        country=country,
        full_name=full_name,
        email=email,
        phone=overrides.pop("phone", "+2348023900964"),
        institution=overrides.pop("institution", "University of Lagos"),
        academic_level=overrides.pop("academic_level", "300 Level"),
        course_of_study=overrides.pop("course_of_study", "Biochemistry"),
        status=status,
        **overrides,
    )


#: A well-formed apply payload. Spread and override one key per test, so a test about
#: the phone rule does not also restate six fields it does not care about.
VALID_PAYLOAD = {
    "country": "NG",
    "full_name": "Chidinma Eze",
    "email": "chidinma@example.com",
    "phone": "+2348023900964",
    "institution": "University of Lagos",
    "academic_level": "300 Level",
    "course_of_study": "Biochemistry",
}
