import pytest
from rest_framework.test import APIClient

PW = "Str0ng!pass9"
NEW = "N3w!pass9word"


@pytest.mark.django_db
def test_password_change_requires_correct_old_password(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password=PW)
    c = APIClient()
    c.force_authenticate(user)

    r = c.post("/api/v1/auth/password/change/",
               {"old_password": "wrong", "new_password": NEW}, format="json")

    assert r.status_code == 400
    assert "old_password" in r.data
    user.refresh_from_db()
    assert user.check_password(PW)          # unchanged


@pytest.mark.django_db
def test_password_change_succeeds_with_correct_old_password(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password=PW)
    c = APIClient()
    c.force_authenticate(user)

    r = c.post("/api/v1/auth/password/change/",
               {"old_password": PW, "new_password": NEW}, format="json")

    assert r.status_code == 200
    user.refresh_from_db()
    assert user.check_password(NEW)


@pytest.mark.django_db
def test_password_change_rejects_weak_new_password(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password=PW)
    c = APIClient()
    c.force_authenticate(user)

    r = c.post("/api/v1/auth/password/change/",
               {"old_password": PW, "new_password": "123"}, format="json")

    assert r.status_code == 400
    assert "new_password" in r.data


@pytest.mark.django_db
def test_password_change_requires_auth():
    r = APIClient().post("/api/v1/auth/password/change/",
                         {"old_password": PW, "new_password": NEW}, format="json")
    assert r.status_code in (401, 403)
