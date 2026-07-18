from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite

from apps.catalog.factories import ProductFactory
from apps.reviews.admin import ReviewAdmin
from apps.reviews.models import Review


@pytest.mark.django_db
def test_admin_approve_action_sets_status_and_recomputes(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    product = ProductFactory()
    review = Review.objects.create(product=product, user=user, rating=4, body="Good")

    admin = ReviewAdmin(Review, AdminSite())
    admin.approve_reviews(request=None, queryset=Review.objects.filter(pk=review.pk))

    review.refresh_from_db()
    product.refresh_from_db()
    assert review.status == "approved"
    assert product.rating_count == 1
    assert product.rating_avg == Decimal("4.00")
