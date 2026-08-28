"""The address a customer and a courier actually read.

Plan-18a's exit-gate walk placed a real order and found the shipped email printing the
street line, a blank line, and nothing else — no recipient, no city, no state, no phone.
The templates read `city` and `region`; `_address_snapshot` writes `area` and `state`.
Nothing failed, because a missing key in a Django template renders as empty string, and
no test had ever compared the two vocabularies.

So these tests pin the CONTRACT rather than the markup: whatever the snapshot writes must
appear in what we send. `test_every_snapshot_key_is_rendered` is the one that would have
caught it, and it will catch the next field added to the snapshot and forgotten here.
"""
import pytest
from django.core import mail

from apps.checkout.services.checkout import _address_snapshot
from apps.notifications.send import send_email

# A full snapshot, in the exact shape `_address_snapshot` produces.
SNAPSHOT = {
    "first_name": "Ada", "last_name": "Walker", "phone": "08031234567",
    "line1": "14 Adeola Odeku Street", "line2": "Flat 3", "country_code": "NG",
    "state": "Lagos", "area": "Ikeja", "postcode": "101241",
}


def _body(template: str, **extra) -> str:
    mail.outbox = []
    send_email(template, "a@b.com", {
        "number": "TC-100044", "placed_at": "01 Aug 2026", "items": [],
        "subtotal": "₦0.00", "shipping_total": "₦0.00", "grand_total": "₦0.00",
        "discount_total": "", "tax_total": "", "delivery_option_name": "Lagos Delivery",
        "tracking_url": "https://x/y", "shipping_address": SNAPSHOT, **extra,
    })
    return mail.outbox[0].body


@pytest.mark.parametrize("template", ["order_confirmation", "order_shipped"])
def test_every_snapshot_key_is_rendered(settings, template):
    """The regression itself. Not 'the template mentions a city' — every VALUE the
    snapshot carries has to reach the customer, or the parcel cannot be delivered."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    body = _body(template, tracking_carrier="GIG", tracking_number="GIG-1")

    for key, value in SNAPSHOT.items():
        assert value in body, f"{template}: snapshot key {key!r} ({value!r}) never rendered"


def test_the_snapshot_keys_are_what_the_templates_expect():
    """Guards the vocabulary from the other end: if `_address_snapshot` is renamed, this
    fails next to the templates that read it rather than silently blanking a live email."""
    from apps.accounts.models import Address

    produced = set(_address_snapshot(Address(
        first_name="A", last_name="B", phone="1", line1="L1", line2="",
        country_code="NG", state_text="Lagos", city_text="Ikeja", postcode="1",
    )))

    assert produced == {
        "first_name", "last_name", "phone", "line1", "line2",
        # The NG landmark (2026-08-28) — "opposite Ikeja City Mall". Carried so the
        # carrier payloads can fold it into the address line they print; whether the
        # customer-facing emails render it is decided by the templates, not here.
        "landmark",
        "country_code", "state", "area", "postcode",
        # The pin (Plan-32b): MACHINE data for the GIG waybill (capture.py reads it
        # from the snapshot), deliberately NOT rendered in any email — coordinates
        # in a customer email are noise, so the render test above excludes them.
        "latitude", "longitude",
    }


def test_an_international_address_skips_what_it_does_not_have(settings):
    """A GB address has no state and a RoW one may have no postcode. Those lines must
    vanish rather than printing a stray comma or a blank line."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []
    sparse = {"first_name": "Jo", "last_name": "Bloggs", "line1": "1 High Street",
              "line2": "", "area": "London", "state": "", "postcode": "", "phone": "",
              "country_code": "GB"}

    send_email("order_confirmation", "a@b.com", {
        "number": "TC-1", "placed_at": "01 Aug 2026", "items": [],
        "subtotal": "£0.00", "shipping_total": "£0.00", "grand_total": "£0.00",
        "discount_total": "", "tax_total": "", "delivery_option_name": "Royal Mail",
        "tracking_url": "https://x/y", "shipping_address": sparse,
    })
    body = mail.outbox[0].body

    assert "Jo Bloggs" in body and "1 High Street" in body and "London" in body
    delivering = body.split("Delivering to:")[1].split("Track your order")[0]
    assert not [line for line in delivering.splitlines() if line.strip() == ","]
    assert "  \n  \n" not in delivering


@pytest.mark.parametrize("template", ["order_confirmation", "order_shipped"])
def test_pickup_orders_say_collect_from_not_delivering_to(settings, template):
    """32b ruling 6: pickup changes the words everywhere — a centre order must never
    print doorstep language, and the collect instructions carry number + ID."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    body = _body(template, tracking_carrier="GIG", tracking_number="GIG-1",
                 pickup_centre={"id": 540, "name": "GIG Alausa",
                                "address": "Plot Y, Mobolaji Johnson, Alausa Ikeja"})
    assert "Collect from" in body
    assert "GIG Alausa" in body
    assert "photo ID" in body
    assert "TC-100044" in body
    assert "Delivering to" not in body
