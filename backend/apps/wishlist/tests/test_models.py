import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.wishlist.models import WishlistItem


@pytest.mark.django_db
def test_wishlist_item_is_unique_per_user_and_variant(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    variant = ProductVariantFactory()

    WishlistItem.objects.create(user=user, variant=variant)
    with pytest.raises(Exception):  # IntegrityError under the unique_together
        WishlistItem.objects.create(user=user, variant=variant)


@pytest.mark.django_db
def test_two_users_can_wishlist_the_same_variant(django_user_model):
    u1 = django_user_model.objects.create_user(email="a@b.com", password="pw")
    u2 = django_user_model.objects.create_user(email="b@b.com", password="pw")
    variant = ProductVariantFactory()

    WishlistItem.objects.create(user=u1, variant=variant)
    WishlistItem.objects.create(user=u2, variant=variant)  # no clash

    assert WishlistItem.objects.count() == 2
