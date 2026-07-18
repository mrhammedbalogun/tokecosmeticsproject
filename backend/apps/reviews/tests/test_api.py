import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.reviews.models import Review


def _delivered_order_for(user, variant, status="delivered"):
    ng = Country.objects.get(code="NG")
    order = OrderFactory(number=f"TC-{variant.id:06d}", country=ng, currency=ng.currency,
                         user=user, email=user.email, status=status)
    OrderItem.objects.create(order=order, variant=variant, product_name=variant.product.name,
                             unit_price=1, line_total=1, quantity=1)
    return order


@pytest.mark.django_db
def test_verified_purchaser_can_post_a_pending_review(django_user_model):
    variant = ProductVariantFactory()
    product = variant.product
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    _delivered_order_for(user, variant)
    c = APIClient()
    c.force_authenticate(user)

    r = c.post(f"/api/v1/products/{product.slug}/reviews/",
               {"rating": 5, "title": "Love it", "body": "Great product"}, format="json")

    assert r.status_code == 201
    review = Review.objects.get(product=product, user=user)
    assert review.status == "pending"


@pytest.mark.django_db
def test_non_purchaser_is_refused(django_user_model):
    variant = ProductVariantFactory()
    product = variant.product
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    c = APIClient()
    c.force_authenticate(user)

    r = c.post(f"/api/v1/products/{product.slug}/reviews/",
               {"rating": 5, "body": "never bought it"}, format="json")

    assert r.status_code == 403
    assert not Review.objects.filter(product=product, user=user).exists()


@pytest.mark.django_db
def test_a_pending_order_does_not_count_as_verified(django_user_model):
    variant = ProductVariantFactory()
    product = variant.product
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    _delivered_order_for(user, variant, status="pending_payment")   # not delivered/completed
    c = APIClient()
    c.force_authenticate(user)

    r = c.post(f"/api/v1/products/{product.slug}/reviews/",
               {"rating": 5, "body": "paid but not delivered"}, format="json")

    assert r.status_code == 403


@pytest.mark.django_db
def test_completed_order_also_counts_as_verified(django_user_model):
    variant = ProductVariantFactory()
    product = variant.product
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    _delivered_order_for(user, variant, status="completed")
    c = APIClient()
    c.force_authenticate(user)

    r = c.post(f"/api/v1/products/{product.slug}/reviews/",
               {"rating": 4, "body": "arrived and completed"}, format="json")

    assert r.status_code == 201


@pytest.mark.django_db
def test_get_lists_only_approved_reviews(django_user_model):
    variant = ProductVariantFactory()
    product = variant.product
    u1 = django_user_model.objects.create_user(email="a@b.com", password="pw")
    u2 = django_user_model.objects.create_user(email="b@b.com", password="pw")
    Review.objects.create(product=product, user=u1, rating=5, body="approved one",
                          status="approved")
    Review.objects.create(product=product, user=u2, rating=1, body="pending one",
                          status="pending")

    r = APIClient().get(f"/api/v1/products/{product.slug}/reviews/")
    assert r.status_code == 200
    bodies = [rv["body"] for rv in r.data]
    assert bodies == ["approved one"]


@pytest.mark.django_db
def test_cannot_review_the_same_product_twice(django_user_model):
    variant = ProductVariantFactory()
    product = variant.product
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    _delivered_order_for(user, variant)
    c = APIClient()
    c.force_authenticate(user)

    c.post(f"/api/v1/products/{product.slug}/reviews/", {"rating": 5, "body": "one"},
           format="json")
    r = c.post(f"/api/v1/products/{product.slug}/reviews/", {"rating": 1, "body": "two"},
               format="json")
    assert r.status_code == 400
