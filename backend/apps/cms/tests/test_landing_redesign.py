"""Landing redesign backend (2026-08-04): video slides, marquee source, curated
Google reviews — the payload the new homepage renders."""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.cms.models import Banner, GoogleReview, GoogleReviewsMeta

pytestmark = pytest.mark.django_db


def test_homepage_carries_video_banners_strip_news_and_reviews():
    Banner.objects.create(title="Clear More. Glow More.", placement="hero",
                          video_url="https://cdn.example/hero.mp4", sort=0)
    Banner.objects.create(title="Free delivery to the UK on all orders",
                          placement="strip", sort=1)
    GoogleReviewsMeta(rating=Decimal("4.8"), review_count_text="300+",
                      profile_url="https://g.page/toke").save()
    GoogleReview.objects.create(author="Adaeze O.", location="Lagos", rating=5,
                                text="Cleared my dark spots.",
                                review_url="https://g.co/kgs/abc")
    GoogleReview.objects.create(author="Hidden", rating=5, text="x",
                                review_url="https://g.co/kgs/off", is_active=False)

    r = APIClient().get("/api/v1/cms/homepage/")
    assert r.status_code == 200
    data = r.json()
    hero = next(b for b in data["banners"] if b["placement"] == "hero")
    assert hero["video_url"] == "https://cdn.example/hero.mp4"
    assert any(b["placement"] == "strip" for b in data["banners"])
    assert data["reviews"]["rating"] == "4.8"
    assert data["reviews"]["count_text"] == "300+"
    assert [i["author"] for i in data["reviews"]["items"]] == ["Adaeze O."]  # inactive hidden


def test_review_admin_rejects_a_non_google_permalink(admin_client_owner=None):
    from apps.cms.admin_serializers import GoogleReviewAdminSerializer

    s = GoogleReviewAdminSerializer(data={"author": "A", "rating": 5, "text": "t",
                                          "review_url": "https://example.com/r/1"})
    assert not s.is_valid()
    assert "review_url" in s.errors

    s2 = GoogleReviewAdminSerializer(data={"author": "A", "rating": 5, "text": "t",
                                           "review_url": "https://g.co/kgs/abc123"})
    assert s2.is_valid(), s2.errors


def test_reviews_meta_is_a_singleton():
    GoogleReviewsMeta(rating=Decimal("4.7"), review_count_text="200+").save()
    GoogleReviewsMeta(rating=Decimal("4.9"), review_count_text="350+").save()
    assert GoogleReviewsMeta.objects.count() == 1
    assert GoogleReviewsMeta.objects.get().review_count_text == "350+"
