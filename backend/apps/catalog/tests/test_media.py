import pytest

from apps.catalog.models import Product, ProductImage, ProductVideo, ProductVariant


@pytest.mark.django_db
def test_image_attaches_to_product_and_optional_variant():
    p = Product.objects.create(name="P", slug="p")
    v = ProductVariant.objects.create(product=p, sku="P-1", name="default", is_default=True)
    img = ProductImage.objects.create(product=p, image="catalog/products/x.jpg", alt="x", variant=v)
    img2 = ProductImage.objects.create(product=p, image="catalog/products/y.jpg", position=1)
    assert set(p.images.all()) == {img, img2}
    assert img.variant == v
    assert img2.variant is None


@pytest.mark.django_db
def test_video_ordering():
    p = Product.objects.create(name="P2", slug="p2")
    ProductVideo.objects.create(product=p, url="https://youtu.be/b", position=1)
    ProductVideo.objects.create(product=p, url="https://youtu.be/a", position=0)
    assert [v.url for v in p.videos.all()] == ["https://youtu.be/a", "https://youtu.be/b"]
