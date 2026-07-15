import pytest

from apps.catalog.models import Brand, Category, Collection, Tag


@pytest.mark.django_db
def test_category_tree_and_ancestors():
    skincare = Category.objects.create(name="Skincare", slug="skincare")
    face = Category.objects.create(name="Face", slug="face", parent=skincare)
    serums = Category.objects.create(name="Serums", slug="serums", parent=face)
    assert serums.parent == face
    assert [c.slug for c in serums.get_ancestors()] == ["skincare", "face"]
    assert list(skincare.children.all()) == [face]
    assert str(serums) == "Serums"


@pytest.mark.django_db
def test_slugs_unique():
    Brand.objects.create(name="Toke", slug="toke")
    with pytest.raises(Exception):
        Brand.objects.create(name="Toke 2", slug="toke")


@pytest.mark.django_db
def test_collection_rule_default_is_manual():
    c = Collection.objects.create(name="New Arrivals", slug="new-arrivals")
    assert c.rule == "manual"
    assert c.is_active is True


@pytest.mark.django_db
def test_tag_basic():
    t = Tag.objects.create(name="Vegan", slug="vegan")
    assert str(t) == "Vegan"
