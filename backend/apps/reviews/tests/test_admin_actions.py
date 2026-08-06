"""Django-admin backstop actions (the everyday surface is the admin portal's
Reviews screen — see test_admin_api.py)."""
from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite

from apps.catalog.factories import ProductFactory
from apps.reviews.admin import ReviewAdmin
from apps.reviews.models import Review
from apps.reviews.services import recompute_product_rating


@pytest.mark.django_db
def test_admin_hide_action_pulls_review_out_of_the_rating(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    product = ProductFactory()
    review = Review.objects.create(product=product, user=user, rating=4, body="Good")
    recompute_product_rating(product)

    admin = ReviewAdmin(Review, AdminSite())
    admin.hide_reviews(request=None, queryset=Review.objects.filter(pk=review.pk))

    review.refresh_from_db()
    product.refresh_from_db()
    assert review.status == "hidden"
    assert product.rating_count == 0
    assert product.rating_avg == Decimal("0.00")


@pytest.mark.django_db
def test_admin_unhide_action_restores_the_rating(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    product = ProductFactory()
    review = Review.objects.create(
        product=product, user=user, rating=4, body="Good", status="hidden"
    )
    recompute_product_rating(product)

    admin = ReviewAdmin(Review, AdminSite())
    admin.unhide_reviews(request=None, queryset=Review.objects.filter(pk=review.pk))

    review.refresh_from_db()
    product.refresh_from_db()
    assert review.status == "approved"
    assert product.rating_count == 1
    assert product.rating_avg == Decimal("4.00")
