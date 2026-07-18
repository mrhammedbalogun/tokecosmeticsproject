import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import PriceFactory, ProductVariantFactory
from apps.wishlist.models import WishlistItem


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.mark.django_db
def test_add_and_list_wishlist_with_country_card(django_user_model):
    price = PriceFactory()                       # NGN price on a fresh variant
    variant = price.variant
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    c = _client(user)

    r = c.post("/api/v1/me/wishlist/", {"sku": variant.sku}, format="json",
               HTTP_X_COUNTRY="NG")
    assert r.status_code == 201

    lst = c.get("/api/v1/me/wishlist/", HTTP_X_COUNTRY="NG")
    assert lst.status_code == 200
    assert len(lst.data) == 1
    item = lst.data[0]
    assert item["sku"] == variant.sku
    assert item["product"]["from_price"] is not None    # resolved per country
    assert item["product"]["currency"] == "NGN"


@pytest.mark.django_db
def test_adding_the_same_variant_twice_is_idempotent(django_user_model):
    variant = ProductVariantFactory()
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    c = _client(user)

    a = c.post("/api/v1/me/wishlist/", {"sku": variant.sku}, format="json")
    b = c.post("/api/v1/me/wishlist/", {"sku": variant.sku}, format="json")
    assert a.status_code == 201
    assert b.status_code in (200, 201)                  # no crash, no duplicate
    assert WishlistItem.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_delete_removes_only_the_callers_item(django_user_model):
    variant = ProductVariantFactory()
    owner = django_user_model.objects.create_user(email="o@b.com", password="pw")
    other = django_user_model.objects.create_user(email="x@b.com", password="pw")
    WishlistItem.objects.create(user=owner, variant=variant)

    # another user deleting it must not touch the owner's item
    assert _client(other).delete(f"/api/v1/me/wishlist/{variant.sku}/").status_code == 404
    assert WishlistItem.objects.filter(user=owner).count() == 1

    assert _client(owner).delete(f"/api/v1/me/wishlist/{variant.sku}/").status_code == 204
    assert WishlistItem.objects.filter(user=owner).count() == 0


@pytest.mark.django_db
def test_wishlist_requires_auth():
    assert APIClient().get("/api/v1/me/wishlist/").status_code in (401, 403)
