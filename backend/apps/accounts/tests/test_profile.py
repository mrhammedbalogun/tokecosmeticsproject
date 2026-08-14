import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_profile_get_returns_readonly_toke_id(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw",
                                                  first_name="Ada")
    c = APIClient()
    c.force_authenticate(user)

    r = c.get("/api/v1/auth/me/")
    assert r.status_code == 200
    assert r.data["toke_id"].startswith("TK-")
    assert r.data["marketing_consent"] is False


@pytest.mark.django_db
def test_profile_patch_updates_names_phone_consent_but_not_toke_id(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    original_toke = user.toke_id
    c = APIClient()
    c.force_authenticate(user)

    r = c.patch("/api/v1/auth/me/", {
        "first_name": "Ada", "last_name": "Obi", "phone": "+2348099998888",
        "whatsapp": "+234 809 999 8887",
        "marketing_consent": True, "toke_id": "TK-HACKED", "email": "evil@b.com",
    }, format="json")

    assert r.status_code == 200
    user.refresh_from_db()
    assert user.first_name == "Ada"
    assert user.last_name == "Obi"
    assert user.phone == "+2348099998888"
    assert user.whatsapp == "+2348099998887"    # formatting noise normalised away
    assert user.marketing_consent is True
    assert user.toke_id == original_toke        # read-only, ignored
    assert user.email == "a@b.com"              # read-only, ignored


@pytest.mark.django_db
def test_profile_patch_rejects_number_without_country_code(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    c = APIClient()
    c.force_authenticate(user)

    r = c.patch("/api/v1/auth/me/", {"phone": "08099998888"}, format="json")
    assert r.status_code == 400
    assert "country code" in str(r.data["phone"][0])


@pytest.mark.django_db
def test_profile_patch_grandfathers_unchanged_legacy_phone(django_user_model):
    """A WordPress-era national number must not block an unrelated profile edit —
    only a NEW value has to be E.164."""
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    django_user_model.objects.filter(pk=user.pk).update(phone="08099998888")
    user.refresh_from_db()   # force_authenticate hands THIS object to the serializer
    c = APIClient()
    c.force_authenticate(user)

    r = c.patch("/api/v1/auth/me/", {
        "first_name": "Ada", "phone": "08099998888",
    }, format="json")
    assert r.status_code == 200
    user.refresh_from_db()
    assert user.first_name == "Ada"
    assert user.phone == "08099998888"


@pytest.mark.django_db
def test_profile_patch_can_clear_numbers(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    django_user_model.objects.filter(pk=user.pk).update(
        phone="+2348099998888", whatsapp="+2348099998888",
    )
    c = APIClient()
    c.force_authenticate(user)

    r = c.patch("/api/v1/auth/me/", {"phone": "", "whatsapp": ""}, format="json")
    assert r.status_code == 200
    user.refresh_from_db()
    assert user.phone == ""
    assert user.whatsapp == ""
