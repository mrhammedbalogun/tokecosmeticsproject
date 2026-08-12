"""`ProductVideo` as the Videos tab's resource: attach, reorder, detach.

The BYTES are not tested here — they go browser → S3 through the cms ticket/finalize
pair, which `apps/cms/tests` covers. What this file pins is the ATTACH surface: which
library assets may be bound to a product, that the binding cannot silently move, and
the scope arrangement the whole tab stands on (see the tripwire at the bottom).
"""
import pytest
from rest_framework.test import APIClient

from apps.accounts.rbac import SCOPE_GRANTS
from apps.catalog.factories import ProductFactory
from apps.catalog.models import ProductVideo
from apps.catalog.tests.factories_admin import staff_user
from apps.cms.models import MediaAsset

pytestmark = pytest.mark.django_db


def _video_asset(name="clip.mp4"):
    return MediaAsset.objects.create(
        file=f"catalog/library/{name}", kind=MediaAsset.VIDEO, original_name=name
    )


@pytest.fixture
def admin_client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def test_admin_attaches_a_library_video(admin_client):
    product = ProductFactory()
    asset = _video_asset()
    r = admin_client.post(
        "/api/v1/admin/videos/",
        {"product": product.id, "asset": asset.id},
        format="json",
    )
    assert r.status_code == 201
    assert r.data["asset"] == asset.id
    # The tab previews rows straight from the list response — the URL must be there.
    assert r.data["file"].endswith("catalog/library/clip.mp4")


def test_an_image_asset_is_refused(admin_client):
    product = ProductFactory()
    asset = MediaAsset.objects.create(file="catalog/library/a.png", kind=MediaAsset.IMAGE)
    r = admin_client.post(
        "/api/v1/admin/videos/",
        {"product": product.id, "asset": asset.id},
        format="json",
    )
    assert r.status_code == 400
    assert "image" in str(r.data["asset"][0])


def test_videos_filter_by_product(admin_client):
    p1, p2 = ProductFactory(), ProductFactory()
    mine = ProductVideo.objects.create(product=p1, asset=_video_asset("mine.mp4"))
    ProductVideo.objects.create(product=p2, asset=_video_asset("other.mp4"))
    r = admin_client.get(f"/api/v1/admin/videos/?product={p1.id}")
    assert [row["id"] for row in r.data["results"]] == [mine.id]


def test_patch_reorders_but_cannot_move_to_another_product(admin_client):
    p1, p2 = ProductFactory(), ProductFactory()
    video = ProductVideo.objects.create(product=p1, asset=_video_asset())

    ok = admin_client.patch(
        f"/api/v1/admin/videos/{video.id}/", {"position": 3}, format="json"
    )
    assert ok.status_code == 200 and ok.data["position"] == 3

    moved = admin_client.patch(
        f"/api/v1/admin/videos/{video.id}/", {"product": p2.id}, format="json"
    )
    assert moved.status_code == 400
    video.refresh_from_db()
    assert video.product == p1


def test_delete_detaches_but_keeps_the_library_asset(admin_client):
    product = ProductFactory()
    asset = _video_asset()
    video = ProductVideo.objects.create(product=product, asset=asset)
    r = admin_client.delete(f"/api/v1/admin/videos/{video.id}/")
    assert r.status_code == 204
    # Detach deletes the BINDING only: the asset stays in the library (which has no
    # delete of its own — see MediaAsset's docstring) and other products may use it.
    assert MediaAsset.objects.filter(id=asset.id).exists()


def test_products_manage_holders_can_reach_the_upload_endpoints():
    """THE TRIPWIRE the rbac.py comment points at.

    The Videos tab uploads through `marketing.manage` endpoints and attaches through
    `products.manage` ones. That is only coherent while everyone who can attach can
    also upload. The day these grants split, this fails, and the fix is NOT to edit
    this assertion — it is to give the media endpoints the OR-of-scopes treatment the
    `MediaAssetAdminViewSet` docstring deliberately deferred.
    """
    assert SCOPE_GRANTS["products.manage"] <= SCOPE_GRANTS["marketing.manage"]


def test_detail_api_exposes_videos():
    """The public half: a product's videos reach the storefront payload with a URL."""
    from decimal import Decimal

    from apps.catalog.factories import PriceFactory, ProductVariantFactory

    product = ProductFactory()
    PriceFactory(variant=ProductVariantFactory(product=product), amount=Decimal("1000"))
    ProductVideo.objects.create(product=product, asset=_video_asset())

    r = APIClient().get(f"/api/v1/products/{product.slug}/")
    assert r.status_code == 200
    assert [v["url"].endswith("catalog/library/clip.mp4") for v in r.data["videos"]] == [True]
