"""The admin portal's review-management surface: list, hide/unhide (PATCH status),
delete. Role coverage lives in test_admin_role_matrix; audit coverage in test_audit."""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import ProductFactory
from apps.catalog.tests.factories_admin import staff_user
from apps.reviews.models import Review
from apps.reviews.services import recompute_product_rating

pytestmark = pytest.mark.django_db


def _review(django_user_model, product=None, email="buyer@x.com", rating=5,
             status="approved", body="nice"):
    user = django_user_model.objects.create_user(
        email=email, password="pw", first_name="Ada"
    )
    product = product or ProductFactory()
    review = Review.objects.create(
        product=product, user=user, rating=rating, body=body, status=status
    )
    recompute_product_rating(product)
    return review


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def test_requires_staff():
    assert APIClient().get("/api/v1/admin/reviews/").status_code in (401, 403)


def test_list_carries_product_and_author_context(client, django_user_model):
    review = _review(django_user_model)

    r = client.get("/api/v1/admin/reviews/")

    assert r.status_code == 200
    row = r.data["results"][0]
    assert row["product_name"] == review.product.name
    assert row["product_slug"] == review.product.slug
    assert row["author_name"] == "Ada"
    assert row["author_email"] == "buyer@x.com"
    assert row["status"] == "approved"


def test_list_filters_by_status(client, django_user_model):
    _review(django_user_model, email="a@x.com", status="approved")
    hidden = _review(django_user_model, email="b@x.com", status="hidden")

    r = client.get("/api/v1/admin/reviews/?status=hidden")

    assert [row["id"] for row in r.data["results"]] == [hidden.id]


def test_hide_pulls_the_review_out_of_the_public_list_and_rating(
    client, django_user_model,
):
    review = _review(django_user_model, rating=4)
    product = review.product
    assert product.rating_count == 1

    r = client.patch(f"/api/v1/admin/reviews/{review.id}/", {"status": "hidden"},
                     format="json")

    assert r.status_code == 200
    review.refresh_from_db()
    product.refresh_from_db()
    assert review.status == "hidden"
    assert product.rating_count == 0
    assert product.rating_avg == Decimal("0.00")
    public = APIClient().get(f"/api/v1/products/{product.slug}/reviews/")
    assert public.data == []


def test_unhide_restores_the_review_and_rating(client, django_user_model):
    review = _review(django_user_model, rating=4, status="hidden")
    product = review.product

    r = client.patch(f"/api/v1/admin/reviews/{review.id}/", {"status": "approved"},
                     format="json")

    assert r.status_code == 200
    product.refresh_from_db()
    assert product.rating_count == 1
    assert product.rating_avg == Decimal("4.00")


def test_patch_cannot_rewrite_the_customers_words(client, django_user_model):
    review = _review(django_user_model, rating=5, body="original words")

    r = client.patch(
        f"/api/v1/admin/reviews/{review.id}/",
        {"status": "hidden", "body": "staff-edited", "rating": 1},
        format="json",
    )

    assert r.status_code == 200
    review.refresh_from_db()
    assert review.body == "original words"   # read-only: ignored, not applied
    assert review.rating == 5


def test_delete_removes_the_review_and_recomputes(client, django_user_model):
    review = _review(django_user_model, rating=2)
    product = review.product

    r = client.delete(f"/api/v1/admin/reviews/{review.id}/")

    assert r.status_code == 204
    assert not Review.objects.filter(pk=review.pk).exists()
    product.refresh_from_db()
    assert product.rating_count == 0


def test_no_create_route(client):
    r = client.post("/api/v1/admin/reviews/", {"rating": 5, "body": "x"}, format="json")
    assert r.status_code == 405
