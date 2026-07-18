from decimal import Decimal

import pytest

from apps.catalog.factories import ProductFactory
from apps.reviews.models import Review
from apps.reviews.services import recompute_product_rating


@pytest.mark.django_db
def test_review_is_born_pending(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    product = ProductFactory()
    review = Review.objects.create(product=product, user=user, rating=5, body="Great")
    assert review.status == "pending"


@pytest.mark.django_db
def test_one_review_per_user_per_product(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    product = ProductFactory()
    Review.objects.create(product=product, user=user, rating=5, body="A")
    with pytest.raises(Exception):     # IntegrityError under unique_together
        Review.objects.create(product=product, user=user, rating=3, body="B")


@pytest.mark.django_db
def test_recompute_counts_only_approved(django_user_model):
    product = ProductFactory()
    u1 = django_user_model.objects.create_user(email="a@b.com", password="pw")
    u2 = django_user_model.objects.create_user(email="b@b.com", password="pw")
    u3 = django_user_model.objects.create_user(email="c@b.com", password="pw")
    Review.objects.create(product=product, user=u1, rating=5, body="x", status="approved")
    Review.objects.create(product=product, user=u2, rating=3, body="y", status="approved")
    Review.objects.create(product=product, user=u3, rating=1, body="z", status="pending")

    recompute_product_rating(product)

    product.refresh_from_db()
    assert product.rating_count == 2                 # pending excluded
    assert product.rating_avg == Decimal("4.00")     # (5+3)/2


@pytest.mark.django_db
def test_recompute_with_no_approved_reviews_resets_to_zero(django_user_model):
    product = ProductFactory()
    product.rating_avg = Decimal("4.00")
    product.rating_count = 3
    product.save()

    recompute_product_rating(product)

    product.refresh_from_db()
    assert product.rating_avg == Decimal("0.00")
    assert product.rating_count == 0
