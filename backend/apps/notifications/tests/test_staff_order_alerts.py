"""The staff order alerts, end to end: they fire at the right moment, they reach the
subscriber list and nobody else, and they carry nothing that a bare address must not
hold.

Renders the real templates against a real order, for the reason
`apps/orders/tests/test_emails.py` states: a template that renders only under a mock is a
template that breaks in production.
"""
import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from apps.core.models import Country
from apps.notifications.models import NotificationRecipient
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.orders.state import transition_by_id
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture(autouse=True)
def _locmem(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.ADMIN_URL = "https://admin.example.com"


def _order(number="TC-900001", status="pending_payment", **kw):
    ng = Country.objects.get(code="NG")
    order = OrderFactory(
        number=number, country=ng, currency=ng.currency, status=status,
        email="buyer@x.com", phone="+2348012345678",
        grand_total="25000.00", subtotal="24000.00", shipping_total="1000.00",
        delivery_option_name="Lagos Island Same-Day",
        # THE REAL CHECKOUT SNAPSHOT KEYS. `_address_snapshot` writes `area` and
        # `state`, never `city`/`region` — an earlier draft of this test invented the
        # latter and passed while the production code, which had guessed the same wrong
        # names, would have printed nothing but the country for every real order. The
        # same mistake is recorded at the top of `templates/email/_address.txt`.
        shipping_address={"first_name": "Adaeze", "last_name": "Okonkwo",
                          "line1": "1 Awolowo Rd", "area": "Ikoyi",
                          "state": "Lagos", "country_code": "NG"},
        **kw,
    )
    OrderItem.objects.create(order=order, product_name="Shea Butter", variant_name="200ml",
                             sku="SB-200", unit_price="12000.00", line_total="24000.00",
                             quantity=2)
    return order


def _subscribe(event="order.paid", email="packing@x.com"):
    """A CONFIRMED external subscriber.

    `confirmed_at` is set here because an external address receives nothing until it has
    clicked its link (`test_confirmation.py` owns that gate). These tests are about what
    the alerts CONTAIN and when they fire, so they need a subscriber who is actually
    receiving — leaving it unconfirmed silently empties every outbox in this file.
    """
    return NotificationRecipient.objects.create(
        event=event, email=email, confirmed_at=timezone.now()
    )


def test_no_subscribers_means_the_customer_still_gets_their_confirmation(
    django_capture_on_commit_callbacks,
):
    """The staff alert is an extra effect on the `processing` transition, and it must not
    be able to cost the customer their email — including by there being nobody to tell."""
    order = _order()
    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")
    assert [m.to for m in mail.outbox] == [["buyer@x.com"]]


def test_a_subscriber_is_emailed_when_payment_is_confirmed(
    django_capture_on_commit_callbacks,
):
    _subscribe()
    order = _order()
    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = [m for m in mail.outbox if m.to == ["packing@x.com"]]
    assert len(staff_mail) == 1
    assert order.number in staff_mail[0].subject
    assert "Payment confirmed" in staff_mail[0].subject
    assert "Shea Butter" in staff_mail[0].body
    assert "₦25,000.00" in staff_mail[0].body


def test_each_subscriber_gets_their_own_message(django_capture_on_commit_callbacks):
    """One message per recipient, never one message with several addresses in `to`. A
    shared `To:` header publishes the whole subscriber list to an external bookkeeper,
    and one rejected address would fail the send for everybody."""
    _subscribe(email="a@x.com")
    _subscribe(email="b@x.com")
    order = _order()
    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = [m for m in mail.outbox if m.to != ["buyer@x.com"]]
    assert sorted(m.to[0] for m in staff_mail) == ["a@x.com", "b@x.com"]
    assert all(len(m.to) == 1 for m in staff_mail)


def test_the_staff_email_carries_no_tracking_token(django_capture_on_commit_callbacks):
    """THE LEAK THIS SEPARATE CONTEXT EXISTS TO PREVENT. The customer's context embeds a
    signed, login-free bearer token for the order (`orders/tokens.py`). A subscriber list
    can hold bare addresses with no account behind them, so reusing that context would
    post a working credential to somewhere nobody was ever invited."""
    _subscribe()
    order = _order()
    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    body = staff_mail.body + "".join(a[0] for a in staff_mail.alternatives)
    assert "token=" not in body
    assert "/orders/TC-900001?" not in body


def test_the_staff_email_carries_no_street_address_or_phone(
    django_capture_on_commit_callbacks,
):
    """Town and region only. A compromised external inbox should be worth a list of order
    numbers, not a customer address book."""
    _subscribe()
    order = _order()
    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    body = staff_mail.body + "".join(a[0] for a in staff_mail.alternatives)
    assert "1 Awolowo Rd" not in body
    assert "+2348012345678" not in body
    # But it must say enough to be useful. The NAME is in, deliberately (owner, 2026-08-18)
    # — it is what is written on the parcel — while the street line and phone stay out.
    assert "Adaeze Okonkwo" in body
    assert "Ikoyi" in body
    assert "https://admin.example.com/orders/TC-900001" in body


def test_a_flagged_order_says_so(django_capture_on_commit_callbacks):
    _subscribe()
    order = _order(review_reason="Double payment detected")
    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    assert "Double payment detected" in staff_mail.body


def test_the_late_payment_path_also_notifies(django_capture_on_commit_callbacks):
    """`expired -> processing` is the late-payment re-reserve path. That order needs
    packing exactly like any other, and keying effects on the destination status is what
    stops it being silently skipped."""
    _subscribe()
    order = _order(number="TC-900002", status="expired")
    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")
    assert any(m.to == ["packing@x.com"] for m in mail.outbox)


def test_paid_subscribers_do_not_receive_transfer_alerts(
    django_capture_on_commit_callbacks,
):
    """The two events are separate lists on purpose — whoever packs boxes should not be
    made to read every unpaid bank-transfer order."""
    _subscribe(event="order.awaiting_transfer", email="bank@x.com")
    order = _order()
    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")
    assert not any(m.to == ["bank@x.com"] for m in mail.outbox)


def test_a_deactivated_subscriber_is_skipped(django_capture_on_commit_callbacks):
    person = User.objects.create_user(email="gone@x.com", password="x", is_staff=True)
    NotificationRecipient.objects.create(event="order.paid", user=person)
    person.is_active = False
    person.save(update_fields=["is_active"])

    order = _order()
    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")
    assert not any(m.to == ["gone@x.com"] for m in mail.outbox)


# ── the bank-transfer alert, driven through real checkout ───────────────────────────
#
# Driven through `POST /api/v1/checkout/` rather than by calling the enqueue function,
# because the thing under test is the BRANCH: this alert must fire for a gateway that
# hands the customer payment instructions and must not fire for one that takes the money
# in a redirect. Only the real checkout path exercises that.

def _transfer_world(django_user_model, capture, email):
    """One NG bank-transfer checkout. A trimmed copy of the world in
    `apps/orders/tests/test_order_received_email.py`, which is the same setup."""
    from decimal import Decimal

    from rest_framework.test import APIClient

    from apps.accounts.models import Address
    from apps.carts.factories import CartFactory
    from apps.carts.models import CartItem
    from apps.catalog.factories import ProductVariantFactory
    from apps.core.models import Region
    from apps.delivery.factories import DeliveryOptionFactory
    from apps.inventory.factories import StockItemFactory, WarehouseFactory
    from apps.payments.models import BankAccount, CountryPaymentGateway
    from apps.pricing.models import Price

    country = Country.objects.get(code="NG")
    currency = country.currency
    wh = WarehouseFactory(name="NG WH", location_country="NG", priority=1)
    wh.serves_countries.add(country)
    region = Region.objects.create(country_code="NG", name="Lagos", level="state")
    opt = DeliveryOptionFactory(currency=currency, name="NG Flat", price="1500.00")
    opt.regions.add(region)
    CountryPaymentGateway.objects.update_or_create(
        country=country, gateway="bank_transfer",
        defaults={"is_active": True, "sort_order": 1},
    )
    BankAccount.objects.get_or_create(
        country=country, currency=currency, bank_name="GTB",
        account_name="Toke Cosmetics Ltd", account_number="0123456789",
    )
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=currency, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)

    user = django_user_model.objects.create_user(email=email, password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG",
                                  state_region=region)
    cart = CartFactory(user=user, country=country, currency=currency)
    CartItem.objects.create(cart=cart, variant=variant, quantity=2,
                            unit_price_snapshot="1000.00")

    client = APIClient()
    client.force_authenticate(user)
    with capture(execute=True):
        response = client.post(
            "/api/v1/checkout/",
            {"cart_id": str(cart.id), "address_id": addr.id,
             "delivery_option_id": opt.id, "payment_gateway": "bank_transfer"},
            format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY=f"key-{email}",
        )
    assert response.status_code == 201, response.data
    return response


def test_placing_a_bank_transfer_order_alerts_the_watchers(
    django_user_model, django_capture_on_commit_callbacks,
):
    """THE CIRCLE THIS BREAKS. Before it, the first staff email about a transfer order
    arrived when somebody confirmed its payment — which required already knowing the
    order existed."""
    _subscribe(event="order.awaiting_transfer", email="bank@x.com")
    _transfer_world(django_user_model, django_capture_on_commit_callbacks, "b@x.com")

    staff_mail = [m for m in mail.outbox if m.to == ["bank@x.com"]]
    assert len(staff_mail) == 1
    assert "Awaiting bank transfer" in staff_mail[0].subject

    # THE DEADLINE IS THE ORDER'S OWN, not the prose "24 hours after it was placed" this
    # used to carry. `retry_payment` pushes `reservation_expires_at` forward when the
    # customer switches to a slower method, so the sentence would have understated the
    # real deadline and invited staff to write off an order still holding stock.
    from apps.orders.models import Order

    order = Order.objects.latest("id")
    from apps.orders.emails import _staff_local

    assert f"expires {_staff_local(order.reservation_expires_at)}" in staff_mail[0].body
    assert order.reservation_expires_at is not None


def test_the_paid_list_is_not_told_at_placement(
    django_user_model, django_capture_on_commit_callbacks,
):
    """Nothing is paid yet. Telling the packing list here would have them chasing orders
    that may never be paid for."""
    _subscribe(event="order.paid", email="packing@x.com")
    _transfer_world(django_user_model, django_capture_on_commit_callbacks, "c@x.com")
    assert not any(m.to == ["packing@x.com"] for m in mail.outbox)


def test_the_customer_still_gets_their_payment_instructions(
    django_user_model, django_capture_on_commit_callbacks,
):
    """The staff alert is a second on_commit effect on the same branch, and it must not
    be able to cost the customer the only durable copy of the account number."""
    _subscribe(event="order.awaiting_transfer", email="bank@x.com")
    _transfer_world(django_user_model, django_capture_on_commit_callbacks, "d@x.com")

    customer_mail = [m for m in mail.outbox if m.to == ["d@x.com"]]
    assert len(customer_mail) == 1
    assert "0123456789" in customer_mail[0].body


def test_a_pickup_order_names_the_depot(django_capture_on_commit_callbacks):
    """`GigShipment.centre` is a JSON SNAPSHOT (`{"id", "name", "address"}`), not a
    `GigCentre` row — centres close and move, so the parcel ships to the one that was
    priced. Attribute access on it raises `AttributeError` inside a post-commit hook,
    which is a silent lost email in production. Pinned here as well as in
    `apps/checkout/tests/test_gig_checkout.py`, because that test reaches this code only
    incidentally.

    The depot address IS rendered in full, unlike a customer's: it is a public place, and
    the packer needs to know which one the parcel is routed to.
    """
    from apps.delivery.models import GigShipment

    _subscribe()
    order = _order(number="TC-900003")
    GigShipment.objects.create(
        order=order,
        centre={"id": 7, "name": "Ikeja Centre", "address": "3 Obafemi Awolowo Way"},
        charged="1500.00",
    )

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    assert "Ikeja Centre" in staff_mail.body
    assert "3 Obafemi Awolowo Way" in staff_mail.body
    assert "Collect from" in staff_mail.body


def test_a_migrated_order_still_names_its_town(django_capture_on_commit_callbacks):
    """WooCommerce orders were imported with a DIFFERENT snapshot shape — `city` rather
    than `area` (`migration_wp/transform_orders.py::address_snapshot`). Reading only the
    checkout spelling would leave every legacy order's alert saying "Nigeria" and nothing
    else, and legacy orders are exactly the ones that reach `processing` through the
    `on_hold` triage path."""
    _subscribe()
    order = _order(number="TC-900004")
    order.shipping_address = {"address_1": "9 Old Rd", "city": "Aba", "state": "Abia",
                              "country": "NG"}
    order.save(update_fields=["shipping_address"])

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    assert "Aba, Abia, Nigeria" in staff_mail.body
    assert "9 Old Rd" not in staff_mail.body


# ── the guards Fable's pre-deploy review asked for ──────────────────────────────────

def test_a_broken_staff_alert_cannot_cost_the_customer_their_confirmation(
    django_capture_on_commit_callbacks, monkeypatch,
):
    """THE INVARIANT THAT MATTERS MOST IN THIS FILE.

    `on_commit` callbacks are NOT independent: `run_and_clear_commit_hooks` pops them into
    a local list and a non-robust callback that raises abandons every callback after it.
    The staff alert is registered second precisely because of that — but ordering alone is
    one edit away from being wrong, so `_notify_safely` swallows its own failures too.
    This test breaks the staff path deliberately and asserts the customer is untouched.
    """
    import apps.orders.emails as emails_mod

    _subscribe()
    monkeypatch.setattr(
        emails_mod, "notify_staff",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("broker down")),
    )
    order = _order(number="TC-900005")

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    assert [m.to for m in mail.outbox] == [["buyer@x.com"]]


def test_a_broken_staff_alert_does_not_500_the_checkout(
    django_user_model, django_capture_on_commit_callbacks, monkeypatch,
):
    """The same guard on the placement path, where the blast radius is worse: an
    unhandled exception here propagates into the request that committed, which is a 500
    handed to a customer whose bank-transfer order was just successfully placed."""
    import apps.orders.emails as emails_mod

    _subscribe(event="order.awaiting_transfer", email="bank@x.com")
    monkeypatch.setattr(
        emails_mod, "notify_staff",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("broker down")),
    )

    # Raises if the guard is missing — the response assert inside is 201.
    _transfer_world(django_user_model, django_capture_on_commit_callbacks, "e@x.com")
    assert any(m.to == ["e@x.com"] for m in mail.outbox)


def test_staff_timestamps_are_rendered_in_the_reader_s_timezone(
    django_capture_on_commit_callbacks, settings,
):
    """`TIME_ZONE` is UTC and the people reading these are in Lagos (UTC+1). The
    awaiting-transfer mail asks the reader to reason about a deadline from this
    timestamp, so an hour's drift sends whoever is matching bank statements to the wrong
    hour of the day."""
    from datetime import datetime, timezone as dt_timezone

    settings.STAFF_DISPLAY_TIMEZONE = "Africa/Lagos"
    _subscribe()
    order = _order(number="TC-900006")
    order.placed_at = datetime(2026, 3, 1, 9, 0, tzinfo=dt_timezone.utc)
    order.save(update_fields=["placed_at"])

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    assert "01 Mar 2026, 10:00" in staff_mail.body   # 09:00 UTC == 10:00 WAT
    assert "01 Mar 2026, 09:00" not in staff_mail.body


def test_an_unusable_display_timezone_degrades_instead_of_losing_the_alert(
    django_capture_on_commit_callbacks, settings,
):
    """`_notify_safely` would otherwise swallow a `ZoneInfoNotFoundError` and drop every
    staff alert over a presentation setting."""
    settings.STAFF_DISPLAY_TIMEZONE = "Not/AZone"
    _subscribe()
    order = _order(number="TC-900007")

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    assert any(m.to == ["packing@x.com"] for m in mail.outbox)


# ── product pictures ────────────────────────────────────────────────────────────────

def _order_with_a_real_product(number, subscribe=True):
    """An order whose line points at a real variant with a real image, so the image path
    exercises `ProductImage` rather than a fabricated URL."""
    from io import BytesIO

    from django.core.files.base import ContentFile
    from PIL import Image as PILImage

    from apps.catalog.factories import ProductVariantFactory
    from apps.catalog.models import ProductImage
    from apps.catalog.images import variant_image_path

    variant = ProductVariantFactory()
    buffer = BytesIO()
    PILImage.new("RGB", (1200, 900), (180, 100, 80)).save(buffer, format="JPEG")
    picture = ProductImage(product=variant.product, alt="A jar of shea butter")
    picture.image.save("jar.jpg", ContentFile(buffer.getvalue()), save=False)
    picture.save()

    if subscribe:
        _subscribe()
    order = _order(number=number)
    item = order.items.first()
    item.variant = variant
    item.image_path = variant_image_path(variant)
    item.save(update_fields=["variant", "image_path"])
    return order, picture


def test_the_staff_email_shows_the_product_picture(django_capture_on_commit_callbacks):
    """For the PACKER: matching a jar on the bench to a line on a list is faster by sight,
    and it is the check that catches picking the 50ml instead of the 200ml."""
    order, picture = _order_with_a_real_product("TC-900010")

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    html = "".join(a[0] for a in staff_mail.alternatives)
    assert picture.thumbnail.name in html
    assert 'alt="A jar of shea butter"' in html
    # Explicit dimensions, because Outlook honours the attributes and ignores CSS.
    assert 'width="52" height="52"' in html


def test_the_email_uses_the_thumbnail_not_the_full_size_original(
    django_capture_on_commit_callbacks,
):
    """The whole point of the pipeline: catalogue originals average 549KB, and a mail
    client fetches whatever `src` says with nothing resizing it in between."""
    order, picture = _order_with_a_real_product("TC-900011")

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    html = "".join(a[0] for a in staff_mail.alternatives)
    assert "thumbs" in html
    assert picture.image.name not in html


def test_the_customer_confirmation_shows_the_picture_too(
    django_capture_on_commit_callbacks,
):
    order, picture = _order_with_a_real_product("TC-900012", subscribe=False)

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    customer_mail = next(m for m in mail.outbox if m.to == ["buyer@x.com"])
    html = "".join(a[0] for a in customer_mail.alternatives)
    assert picture.thumbnail.name in html
    assert 'width="64" height="64"' in html


def test_a_line_with_no_picture_still_renders(django_capture_on_commit_callbacks):
    """A deleted product, or any order placed before checkout started snapshotting. The
    row must keep its column alignment rather than shifting the table."""
    _subscribe()
    order = _order(number="TC-900013")  # no variant, no image

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    html = "".join(a[0] for a in staff_mail.alternatives)
    assert "Shea Butter" in html
    # No PRODUCT picture — checked by the thumbnail's own dimensions rather than by
    # "<img" being absent from the document, which it no longer is: the branded shell
    # (`templates/email/base.html`) carries the Toke logo and the social icons on every
    # mail. `52x52` is the line-item thumbnail and nothing else in the mail uses it.
    assert 'width="52" height="52"' not in html


def test_an_old_order_without_a_snapshot_resolves_its_picture_live(
    django_capture_on_commit_callbacks,
):
    """`image_path` was only written from the day checkout started snapshotting it, so
    every earlier order — including every one migrated from WooCommerce — carries "" and
    must fall back to the `variant` FK."""
    order, picture = _order_with_a_real_product("TC-900014")
    item = order.items.first()
    item.image_path = ""
    item.save(update_fields=["image_path"])

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    assert picture.thumbnail.name in "".join(a[0] for a in staff_mail.alternatives)


# ── WHAT THE PACKER NEEDS AT A GLANCE (owner, 2026-08-18) ───────────────────────────
# Customer, payment method and delivery method were the three facts that sent whoever
# reads this alert into the admin. Two were absent from the mail entirely.


def test_the_alert_names_the_customer_the_payment_and_the_delivery_method(
    django_capture_on_commit_callbacks,
):
    _subscribe()
    order = _order()
    Payment.objects.create(
        order=order, gateway="paystack", amount="25000.00", currency=order.currency,
        status="succeeded", idempotency_key="idem-name-1",
    )

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    html = "".join(a[0] for a in staff_mail.alternatives)
    for body in (html, staff_mail.body):
        assert "Adaeze Okonkwo" in body
        # The LABEL, not the gateway code — the same words the customer saw at checkout.
        assert "Card / Paystack" in body
        assert "paystack" not in body
        assert "Lagos Island Same-Day" in body


def test_a_settled_payment_beats_a_newer_failed_one(django_capture_on_commit_callbacks):
    """An order can carry a failed card attempt and a transfer that worked, or a retry
    through a second gateway. "Most recent" would name the gateway that did NOT take the
    money — which is the one answer that sends somebody hunting the wrong bank feed."""
    _subscribe()
    order = _order()
    Payment.objects.create(
        order=order, gateway="bank_transfer", amount="25000.00", currency=order.currency,
        status="succeeded", idempotency_key="idem-settled",
    )
    Payment.objects.create(
        order=order, gateway="paystack", amount="25000.00", currency=order.currency,
        status="failed", idempotency_key="idem-failed-later",
    )

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    html = "".join(a[0] for a in staff_mail.alternatives)
    assert "Bank transfer" in html
    assert "Paystack" not in html


def test_a_freight_payment_never_answers_how_the_order_was_paid(
    django_capture_on_commit_callbacks,
):
    """`purpose="freight"` is a separate charge for shipping. Naming its gateway here
    would answer the question with the wrong payment entirely."""
    _subscribe()
    order = _order()
    Payment.objects.create(
        order=order, gateway="bank_transfer", amount="25000.00", currency=order.currency,
        status="succeeded", purpose="goods", idempotency_key="idem-goods",
    )
    Payment.objects.create(
        order=order, gateway="paystack", amount="3000.00", currency=order.currency,
        status="succeeded", purpose="freight", idempotency_key="idem-freight",
    )

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    html = "".join(a[0] for a in staff_mail.alternatives)
    assert "Bank transfer" in html
    assert "Paystack" not in html


def test_an_order_with_no_name_in_its_snapshot_drops_the_row(
    django_capture_on_commit_callbacks,
):
    """Migrated WooCommerce orders can carry a snapshot with no name. The row has to
    disappear rather than print a blank or an email address."""
    _subscribe()
    order = _order()
    # `_order` pins a snapshot WITH a name, so strip it here rather than fight the
    # factory's kwargs — what matters is the state at the moment the alert renders.
    order.shipping_address = {"line1": "1 Awolowo Rd", "area": "Ikoyi",
                              "state": "Lagos", "country_code": "NG"}
    order.billing_address = {}
    order.save(update_fields=["shipping_address", "billing_address"])

    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing")

    staff_mail = next(m for m in mail.outbox if m.to == ["packing@x.com"])
    html = "".join(a[0] for a in staff_mail.alternatives)
    assert ">Customer</td>" not in html
    assert "buyer@x.com" not in html
