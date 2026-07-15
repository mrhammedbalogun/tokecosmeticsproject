import pytest
from django.contrib.auth import get_user_model


@pytest.mark.django_db
def test_create_user_assigns_toke_id():
    U = get_user_model()
    u = U.objects.create_user(email="A@B.com", password="x")
    assert u.toke_id.startswith("TK-")
    assert u.email == "a@b.com"  # normalized + lowercased
    assert U.USERNAME_FIELD == "email"


@pytest.mark.django_db
def test_email_is_unique():
    U = get_user_model()
    U.objects.create_user(email="a@b.com", password="x")
    with pytest.raises(Exception):
        U.objects.create_user(email="a@b.com", password="y")


@pytest.mark.django_db
def test_superuser_flags():
    U = get_user_model()
    su = U.objects.create_superuser(email="admin@toke.com", password="x")
    assert su.is_staff and su.is_superuser
