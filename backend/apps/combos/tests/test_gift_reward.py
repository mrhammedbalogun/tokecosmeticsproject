"""A combo's reward: a discount, or a gift — never both.

The reason this file exists is a live bundle. Toke's Back-to-School Care Pack gives a
free gift rather than a percentage, and before the reward was a choice the only way to
express that was to pin its price to its own component total by hand. That produced a
combo advertising "Save ₦0 · 0% off" on the shop — a discount claim of nothing, made
because the model had no way to say "the reward is in the parcel".
"""
from decimal import Decimal

import pytest
from django.db.utils import IntegrityError

from apps.combos.models import REWARD_GIFT, Combo, ComboPrice
from apps.combos.services import resolve_combo_price

pytestmark = pytest.mark.django_db


def test_a_gift_combo_charges_what_the_parts_cost(ng, combo):
    """The heart of it: `discount_percent` defaults to 10, so a gift bundle built in the
    admin would quietly give the gift AND 10% off if the reward were not read here."""
    c = combo(discount_percent=10, reward_type=REWARD_GIFT, gift_name="Free shea butter")
    pricing = resolve_combo_price(c, ng)
    assert pricing.components_total == Decimal("2000.00")
    assert pricing.amount == Decimal("2000.00")
    assert pricing.saving == Decimal("0.00")
    assert pricing.saving_percent == Decimal("0.00")


def test_switching_the_reward_back_restores_the_rate(ng, combo):
    """`discount_percent` is left alone rather than zeroed on the row, so a curator who
    tries the gift for a campaign and changes their mind gets their 10% back."""
    c = combo(discount_percent=10, reward_type=REWARD_GIFT, gift_name="Free shea butter")
    assert resolve_combo_price(c, ng).amount == Decimal("2000.00")
    c.reward_type = "discount"
    c.save(update_fields=["reward_type"])
    assert resolve_combo_price(c, ng).amount == Decimal("1800.00")


def test_a_pinned_price_still_wins_for_a_gift_combo(ng, combo):
    """How a gift bundle gets a round number. The saving that produces is real, and is
    reported as one — the shop shows it beside the gift rather than instead of it."""
    c = combo(reward_type=REWARD_GIFT, gift_name="Free shea butter")
    ComboPrice.objects.create(combo=c, country=ng, amount=Decimal("1900.00"))
    pricing = resolve_combo_price(c, ng)
    assert pricing.amount == Decimal("1900.00")
    assert pricing.saving == Decimal("100.00")
    assert pricing.pinned is True


def test_a_gift_combo_cannot_exist_without_a_gift(combo):
    """The database's own backstop. The admin serializer refuses this with a sentence;
    the constraint is what lets every reader treat `reward_type == "gift"` as "there is
    a gift to print"."""
    with pytest.raises(IntegrityError):
        Combo.objects.create(
            name="Nameless gift", slug="nameless-gift", reward_type=REWARD_GIFT
        )


def test_a_whitespace_gift_name_is_not_a_gift(combo):
    """`!= ""` was not enough. A shell or a data migration writing "   " satisfied the
    old constraint and left a live card promising a reward whose name renders as
    nothing — which the storefront would then paper over with a generic fallback, so
    nobody would ever find out."""
    with pytest.raises(IntegrityError):
        Combo.objects.create(
            name="Blank gift", slug="blank-gift", reward_type=REWARD_GIFT, gift_name="   "
        )


def test_a_discount_combo_may_leave_the_gift_fields_empty(ng, combo):
    """The other half of the constraint: it must not make `gift_name` mandatory for the
    twenty bundles that give a percentage."""
    c = combo()
    assert c.gift_name == ""
    assert resolve_combo_price(c, ng).amount == Decimal("1800.00")


class TestPublicPayload:
    """What the storefront is handed — it draws one badge and must not need two
    questions to decide which."""

    def test_a_gift_combo_carries_its_gift(self, client, ng, combo):
        combo(
            slug="gift-box",
            reward_type=REWARD_GIFT,
            gift_name="Free Kids Hair Grow Cream (50ml)",
        )
        body = client.get("/api/v1/combos/gift-box/", HTTP_X_COUNTRY="NG").json()
        assert body["reward_type"] == "gift"
        assert body["gift"]["name"] == "Free Kids Hair Grow Cream (50ml)"
        # Optional, and the card has to cope: a gift with no photograph is a badge.
        assert body["gift"]["image"] is None

    def test_a_discount_combo_carries_no_gift(self, client, ng, combo):
        combo(slug="percent-box")
        body = client.get("/api/v1/combos/percent-box/", HTTP_X_COUNTRY="NG").json()
        assert body["reward_type"] == "discount"
        assert body["gift"] is None

    def test_the_listing_says_it_too(self, client, ng, combo):
        """The homepage row and /combo both read the LIST, so the reward has to be on
        the card payload — not only on the detail page a shopper may never open."""
        combo(slug="gift-box", reward_type=REWARD_GIFT, gift_name="Free shea butter")
        rows = client.get("/api/v1/combos/", HTTP_X_COUNTRY="NG").json()
        row = next(r for r in rows if r["slug"] == "gift-box")
        assert row["reward_type"] == "gift"
        assert row["gift"]["name"] == "Free shea butter"
        # And it is still priced, so the card can print an amount.
        assert row["pricing"]["amount"] == "2000.00"


# ── admin validation: a promise the shop cannot print ───────────────────────────────

@pytest.fixture
def admin_api(db):
    """One client per test. Built as a fixture rather than a helper called twice —
    `staff_user` CREATES the account, so a second call in one test collides on the
    email."""
    from rest_framework.test import APIClient

    from apps.catalog.tests.factories_admin import staff_user

    c = APIClient()
    c.force_authenticate(user=staff_user(email="gift@toke.test"))
    return c


def test_a_gift_combo_must_name_its_gift(admin_api, ng, priced_variant):
    """Refused with a sentence rather than reaching the CHECK constraint as a 500."""
    v = priced_variant("1000.00")
    r = admin_api.post("/api/v1/admin/combos/", {
        "name": "G", "slug": "g", "reward_type": "gift",
        "items": [{"variant": v.id, "quantity": 1}],
    }, format="json")
    assert r.status_code == 400
    assert "gift_name" in r.data


def test_flipping_an_existing_combo_to_gift_needs_a_gift_too(admin_api, ng, combo):
    """A PATCH sends ONE field. Validating `attrs` alone would wave this through and let
    the constraint answer it with a 500 — so the rule reads through the instance."""
    c = combo(slug="flip-me")
    r = admin_api.patch(f"/api/v1/admin/combos/{c.slug}/", {"reward_type": "gift"},
                        format="json")
    assert r.status_code == 400
    assert "gift_name" in r.data

    ok = admin_api.patch(f"/api/v1/admin/combos/{c.slug}/",
                         {"reward_type": "gift", "gift_name": "Free shea butter"},
                         format="json")
    assert ok.status_code == 200
    c.refresh_from_db()
    assert c.reward_type == REWARD_GIFT


def test_clearing_the_gift_on_a_gift_combo_is_refused(admin_api, ng, combo):
    """The mirror case, and the one that reaches a customer: blanking the name would
    leave a live bundle promising a reward the page has nothing to print."""
    c = combo(slug="keep-the-gift", reward_type=REWARD_GIFT, gift_name="Free shea butter")
    r = admin_api.patch(f"/api/v1/admin/combos/{c.slug}/", {"gift_name": "  "},
                       format="json")
    assert r.status_code == 400


def test_switching_to_discount_may_leave_the_gift_behind(admin_api, ng, combo):
    """Not an error: the gift name stays on the row, unused, so a campaign can be turned
    back on without retyping it. Only `reward_type` decides what the shop says."""
    c = combo(slug="was-a-gift", reward_type=REWARD_GIFT, gift_name="Free shea butter")
    r = admin_api.patch(f"/api/v1/admin/combos/{c.slug}/", {"reward_type": "discount"},
                       format="json")
    assert r.status_code == 200
    c.refresh_from_db()
    assert c.gift_name == "Free shea butter"


def test_the_admin_list_renders(admin_api, ng, combo):
    """A GET that nothing else in this suite makes.

    It caught a real 500: `gift_image_url` was declared on the LIST serializer as well as
    the detail one, without being in its `fields`, and DRF asserts on that at render time
    — so every combo list in the admin was a 500 while every unit test still passed. The
    list is the first page a curator opens.
    """
    combo(slug="gift-row", reward_type=REWARD_GIFT, gift_name="Free shea butter")
    combo(slug="percent-row")
    r = admin_api.get("/api/v1/admin/combos/")
    assert r.status_code == 200
    rows = {row["slug"]: row for row in r.data["results"]}
    # The list has to say what each bundle PROMISES — a column reading "10%" against a
    # combo that gives a gift is how this went wrong in the first place.
    assert rows["gift-row"]["reward_type"] == "gift"
    assert rows["gift-row"]["gift_name"] == "Free shea butter"
    assert rows["percent-row"]["reward_type"] == "discount"


def test_the_admin_detail_renders_the_gift_photo_field(admin_api, ng, combo):
    c = combo(slug="gift-detail", reward_type=REWARD_GIFT, gift_name="Free shea butter")
    r = admin_api.get(f"/api/v1/admin/combos/{c.slug}/")
    assert r.status_code == 200
    assert r.data["reward_type"] == "gift"
    assert r.data["gift_image_url"] is None


def test_the_gift_photo_route_uploads_and_clears(admin_api, ng, combo):
    """The only new endpoint, and the same untested-admin-surface gap that produced a
    500 on the combo list. DELETE exists because a gift changes every campaign, and last
    month's sachet left on a bundle now giving something else is a wrong promise."""
    import io

    from PIL import Image

    c = combo(slug="photo-box", reward_type=REWARD_GIFT, gift_name="Free shea butter")
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    buf.seek(0)
    buf.name = "gift.png"

    up = admin_api.post(f"/api/v1/admin/combos/{c.slug}/gift-image/",
                        {"gift_image": buf}, format="multipart")
    assert up.status_code == 200
    assert up.data["gift_image_url"]
    c.refresh_from_db()
    # The S3 rule that has bitten this project twice: anything not under `catalog/`
    # uploads perfectly and then 403s at the CDN, with no error anywhere.
    assert c.gift_image.name.startswith("catalog/combos/gifts/")

    cleared = admin_api.delete(f"/api/v1/admin/combos/{c.slug}/gift-image/")
    assert cleared.status_code == 200
    assert cleared.data["gift_image_url"] is None
    c.refresh_from_db()
    assert not c.gift_image
    # Clearing the FILE never clears the gift — the name is what the badge prints.
    assert c.gift_name == "Free shea butter"


def test_the_gift_photo_route_refuses_an_empty_post(admin_api, ng, combo):
    c = combo(slug="no-file", reward_type=REWARD_GIFT, gift_name="Free shea butter")
    r = admin_api.post(f"/api/v1/admin/combos/{c.slug}/gift-image/", {}, format="multipart")
    assert r.status_code == 400


def test_the_gift_photo_audit_says_which_way(admin_api, ng, combo):
    """Upload and removal are one viewset action with an empty `changes`, so without a
    verb of their own the trail cannot tell them apart."""
    import io

    from PIL import Image

    from apps.core.models import AuditLog

    c = combo(slug="audited-photo", reward_type=REWARD_GIFT, gift_name="Free shea butter")
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    buf.seek(0)
    buf.name = "gift.png"
    admin_api.post(f"/api/v1/admin/combos/{c.slug}/gift-image/", {"gift_image": buf},
                   format="multipart")
    admin_api.delete(f"/api/v1/admin/combos/{c.slug}/gift-image/")

    actions = list(AuditLog.objects.order_by("id").values_list("action", flat=True))
    assert "gift_image_upload" in actions
    assert "gift_image_remove" in actions
