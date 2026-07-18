import pytest
from django.utils import timezone

from apps.accounts.models import Address
from apps.accounts.tasks import anonymize_deleted_accounts
from apps.core.models import Country
from apps.orders.factories import OrderFactory


@pytest.mark.django_db
def test_account_past_30_days_is_anonymised(django_user_model):
    user = django_user_model.objects.create_user(
        email="ada@b.com", password="pw", first_name="Ada", last_name="Obi",
        phone="08012345678",
    )
    user.is_active = False
    user.deletion_requested_at = timezone.now() - timezone.timedelta(days=31)
    user.save()
    Address.objects.create(user=user, line1="1 Allen", country_code="GB",
                           city_text="London", postcode="N1", first_name="Ada", phone="07")
    toke = user.toke_id

    n = anonymize_deleted_accounts()

    assert n == 1
    user.refresh_from_db()
    assert user.email == f"deleted-{toke}@deleted.invalid"
    assert user.first_name == ""
    assert user.last_name == ""
    assert user.phone == ""
    assert user.toke_id == toke                      # opaque id kept
    assert Address.objects.filter(user=user).count() == 0
    assert not user.has_usable_password()


@pytest.mark.django_db
def test_account_within_grace_window_is_untouched(django_user_model):
    user = django_user_model.objects.create_user(email="ada@b.com", password="pw",
                                                  first_name="Ada")
    user.is_active = False
    user.deletion_requested_at = timezone.now() - timezone.timedelta(days=5)
    user.save()

    assert anonymize_deleted_accounts() == 0
    user.refresh_from_db()
    assert user.email == "ada@b.com"


@pytest.mark.django_db
def test_active_account_is_never_anonymised(django_user_model):
    user = django_user_model.objects.create_user(email="ada@b.com", password="pw")
    # No deletion_requested_at, still active.
    assert anonymize_deleted_accounts() == 0
    user.refresh_from_db()
    assert user.email == "ada@b.com"


@pytest.mark.django_db
def test_order_snapshot_pii_is_scrubbed(django_user_model):
    ng = Country.objects.get(code="NG")
    user = django_user_model.objects.create_user(email="ada@b.com", password="pw")
    user.is_active = False
    user.deletion_requested_at = timezone.now() - timezone.timedelta(days=31)
    user.save()
    order = OrderFactory(number="TC-900001", country=ng, currency=ng.currency,
                         user=user, email="ada@b.com", phone="08012345678",
                         shipping_address={"first_name": "Ada", "phone": "080"})

    anonymize_deleted_accounts()

    order.refresh_from_db()
    assert order.email == f"deleted-{user.toke_id}@deleted.invalid"
    assert order.phone == ""
    assert order.shipping_address == {}
    assert order.user_id == user.id     # link kept, PII gone


@pytest.mark.django_db
def test_anonymize_is_idempotent(django_user_model):
    user = django_user_model.objects.create_user(email="ada@b.com", password="pw")
    user.is_active = False
    user.deletion_requested_at = timezone.now() - timezone.timedelta(days=31)
    user.save()

    assert anonymize_deleted_accounts() == 1
    assert anonymize_deleted_accounts() == 0     # already scrubbed, not re-counted
