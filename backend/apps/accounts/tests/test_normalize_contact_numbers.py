"""The legacy-number backfill (normalize_contact_numbers).

The properties that matter: dry-run writes NOTHING, --apply writes E.164, an
unparseable value is left exactly as it was, and already-clean values are not
churned.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.accounts.models import Address


def _run(*args):
    out = StringIO()
    call_command("normalize_contact_numbers", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_dry_run_reports_but_writes_nothing(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    django_user_model.objects.filter(pk=user.pk).update(phone="08034138636")

    out = _run()
    assert "would update 1 row(s)" in out
    user.refresh_from_db()
    assert user.phone == "08034138636"      # untouched without --apply


@pytest.mark.django_db
def test_apply_normalises_ng_national_and_noisy_e164(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    # The two real shapes in the WordPress export: bare national with and
    # without the leading 0, plus a noisy-but-international value.
    django_user_model.objects.filter(pk=user.pk).update(
        phone="08034138636", whatsapp="+234 802 390 0964",
    )
    addr = Address.objects.create(user=user, line1="1 Allen", country_code="NG",
                                  first_name="Ada", phone="07066013538")

    out = _run("--apply")
    assert "updated 2 row(s)" in out
    user.refresh_from_db()
    addr.refresh_from_db()
    assert user.phone == "+2348034138636"
    assert user.whatsapp == "+2348023900964"
    assert addr.phone == "+2347066013538"


@pytest.mark.django_db
def test_unparseable_value_is_left_untouched_and_reported(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    django_user_model.objects.filter(pk=user.pk).update(phone="07")   # the "07" stubs

    out = _run("--apply")
    assert "SKIPPED" in out and "'07'" in out
    user.refresh_from_db()
    assert user.phone == "07"


@pytest.mark.django_db
def test_already_clean_values_are_not_churned(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    django_user_model.objects.filter(pk=user.pk).update(phone="+2348034138636")

    out = _run("--apply")
    assert "updated 0 row(s)" in out
