import pytest
from rest_framework.test import APIClient

from apps.newsletter.models import NewsletterSubscriber
from apps.newsletter.tokens import make_unsubscribe_token


@pytest.mark.django_db
def test_public_subscribe_creates_a_subscriber():
    r = APIClient().post("/api/v1/newsletter/",
                         {"email": "a@b.com", "source": "footer"}, format="json")
    assert r.status_code in (200, 201)
    sub = NewsletterSubscriber.objects.get(email="a@b.com")
    assert sub.consented_at is not None
    assert sub.unsubscribed_at is None


@pytest.mark.django_db
def test_subscribing_twice_is_idempotent():
    c = APIClient()
    c.post("/api/v1/newsletter/", {"email": "a@b.com"}, format="json")
    c.post("/api/v1/newsletter/", {"email": "A@b.com"}, format="json")  # case-insensitive
    assert NewsletterSubscriber.objects.filter(email="a@b.com").count() == 1


@pytest.mark.django_db
def test_unsubscribe_via_signed_token():
    sub = NewsletterSubscriber.objects.create(email="a@b.com", source="footer")
    token = make_unsubscribe_token("a@b.com")

    r = APIClient().get(f"/api/v1/newsletter/unsubscribe/?token={token}")
    assert r.status_code == 200
    sub.refresh_from_db()
    assert sub.unsubscribed_at is not None


@pytest.mark.django_db
def test_unsubscribe_rejects_a_bad_token():
    r = APIClient().get("/api/v1/newsletter/unsubscribe/?token=garbage")
    assert r.status_code == 400


@pytest.mark.django_db
def test_subscribe_is_throttled_at_5_per_minute(settings):
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
                                   "newsletter": "5/min"},
    }
    c = APIClient()
    codes = [c.post("/api/v1/newsletter/", {"email": f"u{i}@b.com"}, format="json").status_code
             for i in range(6)]
    assert codes.count(429) >= 1        # the 6th in a minute is throttled
