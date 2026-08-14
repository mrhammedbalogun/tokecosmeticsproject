import pytest
from django.core import mail
from rest_framework.test import APIClient

PW = "Str0ng!pass9"


@pytest.mark.django_db
def test_register_login_me_flow():
    c = APIClient()
    r = c.post(
        "/api/v1/auth/register/",
        {"email": "a@b.com", "password": PW, "first_name": "A"},
        format="json",
    )
    assert r.status_code == 201

    r = c.post("/api/v1/auth/token/", {"email": "a@b.com", "password": PW}, format="json")
    assert r.status_code == 200
    assert "access" in r.data and "refresh" in r.data

    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
    me = c.get("/api/v1/auth/me/")
    assert me.status_code == 200
    assert me.data["email"] == "a@b.com"
    assert me.data["toke_id"].startswith("TK-")


@pytest.mark.django_db
def test_register_normalises_phone_and_whatsapp_to_e164(django_user_model):
    c = APIClient()
    r = c.post(
        "/api/v1/auth/register/",
        {
            "email": "a@b.com", "password": PW, "first_name": "A",
            # Formatting noise in, strict E.164 out.
            "phone": "+234 802 390-0964", "whatsapp": "+1 (415) 555-2671",
        },
        format="json",
    )
    assert r.status_code == 201
    user = django_user_model.objects.get(email="a@b.com")
    assert user.phone == "+2348023900964"
    assert user.whatsapp == "+14155552671"


@pytest.mark.django_db
def test_register_rejects_phone_without_country_code():
    c = APIClient()
    r = c.post(
        "/api/v1/auth/register/",
        {"email": "a@b.com", "password": PW, "first_name": "A", "phone": "08023900964"},
        format="json",
    )
    assert r.status_code == 400
    assert "country code" in str(r.data["phone"])


@pytest.mark.django_db
def test_duplicate_email_clean_400():
    c = APIClient()
    payload = {"email": "a@b.com", "password": PW}
    c.post("/api/v1/auth/register/", payload, format="json")
    r = c.post("/api/v1/auth/register/", payload, format="json")
    assert r.status_code == 400
    assert "email" in r.data
    assert "Account already exists" in str(r.data["email"])


@pytest.mark.django_db
def test_logout_blacklists_refresh():
    c = APIClient()
    c.post("/api/v1/auth/register/", {"email": "a@b.com", "password": PW}, format="json")
    tok = c.post("/api/v1/auth/token/", {"email": "a@b.com", "password": PW}, format="json").data
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok['access']}")
    out = c.post("/api/v1/auth/logout/", {"refresh": tok["refresh"]}, format="json")
    assert out.status_code == 205
    # A blacklisted refresh can no longer be used.
    again = c.post("/api/v1/auth/token/refresh/", {"refresh": tok["refresh"]}, format="json")
    assert again.status_code == 401


@pytest.mark.django_db
def test_password_reset_sends_email(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []
    c = APIClient()
    c.post("/api/v1/auth/register/", {"email": "a@b.com", "password": PW}, format="json")
    mail.outbox = []  # registration now sends a verify-email (Plan-11 Task 12); isolate the reset mail
    r = c.post("/api/v1/auth/password/reset/", {"email": "a@b.com"}, format="json")
    assert r.status_code == 200
    assert len(mail.outbox) == 1
    assert "a@b.com" in mail.outbox[0].to
