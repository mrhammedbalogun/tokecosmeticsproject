"""The two surfaces: what a shopper can see, and what a curator can build."""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.combos.models import Combo, ComboPrice
from apps.core.models import Country

pytestmark = pytest.mark.django_db


# ── public ──────────────────────────────────────────────────────────────────────────

def test_the_list_shows_a_priced_bundle_with_its_saving(ng, combo):
    combo(name="Glow Kit")
    r = APIClient().get("/api/v1/combos/", HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    row = r.data[0]
    assert row["name"] == "Glow Kit"
    assert row["pricing"] == {
        "amount": "1800.00", "components_total": "2000.00",
        "saving": "200.00", "saving_percent": "10.00", "currency": "NGN",
    }
    assert row["item_count"] == 3  # 1 + 2 — units in the box, not rows
    assert row["in_stock"] is True


def test_a_draft_combo_is_invisible_to_shoppers(ng, combo):
    combo(status="draft")
    assert APIClient().get("/api/v1/combos/", HTTP_X_COUNTRY="NG").data == []


def test_a_combo_withdrawn_from_this_market_is_a_404_not_a_stub(ng, combo):
    """A stub page saying "not available here" would be indexed as one."""
    c = combo()
    c.available_countries.add(Country.objects.get(code="GB"))
    assert APIClient().get(f"/api/v1/combos/{c.slug}/", HTTP_X_COUNTRY="NG").status_code == 404


def test_the_detail_page_names_the_variant_options_in_the_box(ng, combo):
    c = combo()
    item = c.items.first()
    item.variant.option_values = {"Size": "500g", "Pricing option": "Pieces"}
    item.variant.save()

    r = APIClient().get(f"/api/v1/combos/{c.slug}/", HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    picked = next(i for i in r.data["items"] if i["sku"] == item.variant.sku)
    assert picked["option_values"] == {"Size": "500g", "Pricing option": "Pieces"}
    assert picked["quantity"] == 1
    assert r.data["max_quantity"] > 0


# ── cart endpoints ──────────────────────────────────────────────────────────────────

def test_adding_a_combo_over_http_returns_the_grouped_cart(ng, combo):
    c = combo()
    client = APIClient()
    r = client.post("/api/v1/cart/combos/", {"combo_slug": c.slug, "quantity": 2},
                    format="json", HTTP_X_COUNTRY="NG")
    assert r.status_code == 200, r.data
    assert r.data["combo_discount"] == "400.00"
    assert r.data["total"] == "3600.00"
    group_id = r.data["combos"][0]["group_id"]

    r = client.patch(f"/api/v1/cart/combos/{group_id}/", {"quantity": 1}, format="json",
                     HTTP_X_COUNTRY="NG", HTTP_X_CART_ID=r.data["id"])
    assert r.data["combos"][0]["quantity"] == 1

    r = client.delete(f"/api/v1/cart/combos/{group_id}/", HTTP_X_COUNTRY="NG",
                      HTTP_X_CART_ID=r.data["id"])
    assert r.data["combos"] == []


def test_adding_a_combo_not_sold_here_is_refused_with_a_code(ng, combo):
    c = combo()
    c.available_countries.add(Country.objects.get(code="GB"))
    r = APIClient().post("/api/v1/cart/combos/", {"combo_slug": c.slug},
                         format="json", HTTP_X_COUNTRY="NG")
    assert r.status_code == 409
    assert r.data["code"] == "combo_unavailable"


# ── admin ───────────────────────────────────────────────────────────────────────────

def _admin():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def test_a_curator_builds_a_combo_in_one_request(ng, priced_variant):
    a, b = priced_variant("1000.00"), priced_variant("500.00")
    r = _admin().post("/api/v1/admin/combos/", {
        "name": "Glow Kit", "slug": "glow-kit", "status": "active",
        "discount_percent": "15.00",
        "items": [{"variant": a.id, "quantity": 1}, {"variant": b.id, "quantity": 2}],
        "available_countries": ["NG"],
    }, format="json")
    assert r.status_code == 201, r.data
    combo = Combo.objects.get(slug="glow-kit")
    assert combo.items.count() == 2
    assert r.data["pricing"]["NG"]["amount"] == "1700.00"  # 15% off 2,000
    assert r.data["pricing"]["NG"]["pinned"] is False


def test_pinning_a_market_price_survives_a_component_repricing(ng, priced_variant):
    a = priced_variant("1000.00")
    client = _admin()
    r = client.post("/api/v1/admin/combos/", {
        "name": "Pinned", "slug": "pinned", "status": "active",
        "items": [{"variant": a.id, "quantity": 2}],
        "prices": [{"country": "NG", "amount": "1500.00"}],
    }, format="json")
    assert r.status_code == 201, r.data
    assert r.data["pricing"]["NG"]["amount"] == "1500.00"

    a.prices.update(amount=Decimal("1200.00"))
    r = client.get("/api/v1/admin/combos/pinned/")
    assert r.data["pricing"]["NG"]["amount"] == "1500.00"
    assert r.data["pricing"]["NG"]["components_total"] == "2400.00"


def test_a_patch_that_omits_items_leaves_the_bundle_intact(ng, combo):
    """Flipping `status` must not silently empty the box."""
    c = combo(status="draft")
    r = _admin().patch(f"/api/v1/admin/combos/{c.slug}/", {"status": "active"}, format="json")
    assert r.status_code == 200, r.data
    assert c.items.count() == 2


def test_the_same_variant_twice_is_refused_by_name(ng, priced_variant):
    a = priced_variant("1000.00")
    r = _admin().post("/api/v1/admin/combos/", {
        "name": "Dupe", "slug": "dupe",
        "items": [{"variant": a.id, "quantity": 1}, {"variant": a.id, "quantity": 1}],
    }, format="json")
    assert r.status_code == 400
    assert a.sku in str(r.data)


def test_the_product_picker_returns_variants_priced_per_market(ng, priced_variant):
    a = priced_variant("1000.00")
    a.product.name = "Carrot Shea Butter"
    a.product.save()
    r = _admin().get("/api/v1/admin/combos/product-search/?q=carrot")
    assert r.status_code == 200
    hit = r.data[0]
    assert hit["name"] == "Carrot Shea Butter"
    assert hit["variants"][0]["prices"]["NG"] == "1000.00"


def test_the_picker_stays_quiet_below_two_characters(ng):
    assert _admin().get("/api/v1/admin/combos/product-search/?q=c").data == []


def test_deleting_a_pinned_price_returns_the_market_to_automatic(ng, combo):
    c = combo()
    ComboPrice.objects.create(combo=c, country=ng, amount=Decimal("1500.00"))
    r = _admin().patch(f"/api/v1/admin/combos/{c.slug}/", {"prices": []}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["pricing"]["NG"]["amount"] == "1800.00"
    assert r.data["pricing"]["NG"]["pinned"] is False
