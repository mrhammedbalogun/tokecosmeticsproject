import pytest
from rest_framework.test import APIClient

PW = "Str0ng!pass9"


@pytest.mark.django_db
def test_deletion_request_deactivates_and_stamps(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password=PW)
    c = APIClient()
    c.force_authenticate(user)

    r = c.post("/api/v1/auth/account/delete/", {"password": PW}, format="json")

    assert r.status_code == 200
    user.refresh_from_db()
    assert user.is_active is False
    assert user.deletion_requested_at is not None


@pytest.mark.django_db
def test_deletion_request_requires_the_current_password(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password=PW)
    c = APIClient()
    c.force_authenticate(user)

    r = c.post("/api/v1/auth/account/delete/", {"password": "wrong"}, format="json")

    assert r.status_code == 400
    user.refresh_from_db()
    assert user.is_active is True
    assert user.deletion_requested_at is None


@pytest.mark.django_db
def test_deactivated_user_cannot_obtain_a_token(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password=PW)
    APIClient().force_authenticate(user)  # request the delete first
    c = APIClient()
    c.force_authenticate(user)
    c.post("/api/v1/auth/account/delete/", {"password": PW}, format="json")

    r = APIClient().post("/api/v1/auth/token/", {"email": "a@b.com", "password": PW},
                         format="json")
    assert r.status_code == 401     # SimpleJWT refuses inactive users
