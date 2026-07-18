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
        "first_name": "Ada", "last_name": "Obi", "phone": "08099998888",
        "marketing_consent": True, "toke_id": "TK-HACKED", "email": "evil@b.com",
    }, format="json")

    assert r.status_code == 200
    user.refresh_from_db()
    assert user.first_name == "Ada"
    assert user.last_name == "Obi"
    assert user.phone == "08099998888"
    assert user.marketing_consent is True
    assert user.toke_id == original_toke        # read-only, ignored
    assert user.email == "a@b.com"              # read-only, ignored
