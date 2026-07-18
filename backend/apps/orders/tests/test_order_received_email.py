"""order_received is the bank-transfer customer's only durable copy of *how to pay*.

Every market transfers differently: a GB domestic transfer needs a sort code, a US ACH
needs a routing number, an international wire needs SWIFT/IBAN. Those live in
`BankAccount.extra` precisely because the set differs per market — so the email must
render whatever that market happens to need, not a fixed three fields. A dropped sort
code is not a cosmetic bug: the customer cannot pay at all, silently, and the order dies
at the reservation TTL 24 hours later.
"""
import pytest
from decimal import Decimal
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.payments.models import BankAccount, CountryPaymentGateway
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def _world(code, *, bank_name, account_number, extra=None, stock=10):
    """One market, seeded end-to-end so `place_order` actually reaches the gateway.

    Mirrors checkout's own `_world()` but parametrised by country: the whole point of
    these tests is the markets that AREN'T Nigeria.
    """
    country = Country.objects.get(code=code)  # seeded in core 0003 — never create
    currency = country.currency
    wh = WarehouseFactory(name=f"{code} WH", location_country=code, priority=1)
    wh.serves_countries.add(country)
    region = Region.objects.create(country_code=code, name=f"{code} Region", level="state")
    opt = DeliveryOptionFactory(currency=currency, name=f"{code} Flat", price="1500.00")
    opt.regions.add(region)
    # Only NG has bank_transfer seeded (payments 0002), but bank transfer is the launch
    # method in every market — checkout refuses a gateway that isn't active for the country.
    CountryPaymentGateway.objects.update_or_create(
        country=country, gateway="bank_transfer",
        defaults={"is_active": True, "sort_order": 1},
    )
    BankAccount.objects.create(
        country=country, currency=currency, bank_name=bank_name,
        account_name="Toke Cosmetics Ltd", account_number=account_number,
        extra=extra or {},
    )
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=currency, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=stock)
    return country, currency, variant, region, opt


def _place(django_user_model, capture, code, world, email):
    country, currency, variant, region, opt = world
    user = django_user_model.objects.create_user(email=email, password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code=code, state_region=region)
    cart = CartFactory(user=user, country=country, currency=currency)
    CartItem.objects.create(cart=cart, variant=variant, quantity=2, unit_price_snapshot="1000.00")

    client = APIClient()
    client.force_authenticate(user)
    with capture(execute=True):  # the email is an on_commit effect — no commit, no mail
        r = client.post(
            "/api/v1/checkout/",
            {"cart_id": str(cart.id), "address_id": addr.id,
             "delivery_option_id": opt.id, "payment_gateway": "bank_transfer"},
            format="json", HTTP_X_COUNTRY=code, HTTP_IDEMPOTENCY_KEY=f"key-{email}",
        )
    assert r.status_code == 201, r.data
    return r


def test_gb_order_received_shows_the_sort_code(
    django_user_model, settings, django_capture_on_commit_callbacks
):
    """No sort code, no UK domestic transfer. The account number alone is unpayable."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    world = _world("GB", bank_name="Barclays", account_number="12345678",
                   extra={"sort_code": "04-00-04"})
    _place(django_user_model, django_capture_on_commit_callbacks, "GB", world, "gb@x.com")

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "04-00-04" in body
    # The digits alone are useless — the customer's banking app asks for a labelled field.
    assert "Sort code" in body


def test_us_order_received_shows_the_routing_number(
    django_user_model, settings, django_capture_on_commit_callbacks
):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    world = _world("US", bank_name="Chase", account_number="987654321",
                   extra={"routing_number": "021000021"})
    _place(django_user_model, django_capture_on_commit_callbacks, "US", world, "us@x.com")

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "021000021" in body
    assert "Routing number" in body


def test_capitalised_extra_keys_survive_as_typed(
    django_user_model, settings, django_capture_on_commit_callbacks
):
    """`IBAN` must not render as "Iban". These keys are acronyms as the bank writes them,
    and a customer matching an email against their banking app reads the label, not just
    the digits. Naive `.capitalize()` lowercases the tail and mangles every one of them.
    """
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    world = _world("ZZ", bank_name="Citi", account_number="55555555",
                   extra={"IBAN": "GB33BUKB20201555555555", "SWIFT BIC": "CITIGB2L",
                          "sort_code": "04-00-04"})
    _place(django_user_model, django_capture_on_commit_callbacks, "ZZ", world, "iban@x.com")

    body = mail.outbox[0].body
    assert "IBAN" in body and "Iban" not in body
    assert "SWIFT BIC" in body and "Swift bic" not in body
    assert "Sort code" in body  # ...while a machine-shaped key is still prettified


def test_a_long_bank_label_still_separates_from_its_value(
    django_user_model, settings, django_capture_on_commit_callbacks
):
    """`ljust` pads a string UP TO a width — it does not guarantee a gap. A label at or
    over the pad width renders flush against its value ("Institution number:003"), and
    these are digits the customer retypes into their banking app.

    Not hypothetical: Canada's real transfer fields are a transit number and an
    institution number, and `institution_number` prettifies to an 18-character label —
    longer than the 16-wide pad. The labels come from BankAccount.extra keys typed in the
    admin, so the template cannot assume any particular length.
    """
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    world = _world("CA", bank_name="RBC", account_number="1234567",
                   extra={"transit_number": "00123", "institution_number": "003"})
    _place(django_user_model, django_capture_on_commit_callbacks, "CA", world, "ca@x.com")

    body = mail.outbox[0].body
    assert "  Institution number: 003" in body
    # ...and the short labels stay aligned with the hardcoded Amount/Reference rows,
    # which are padded by hand and drift the moment the pad width changes.
    assert "  Transit number:  00123" in body
    assert "  Amount:          CA$3,500.00" in body


def test_non_ngn_bank_details_email_asks_for_our_charges(
    django_user_model, settings, django_capture_on_commit_callbacks
):
    """An intl wire under default SHA terms has correspondent fees deducted in flight, so
    the customer sends 50 and 32 lands — which routes every RoW order through the
    discrepancy path. OUR charges (sender pays all fees) is the only lever without code."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    world = _world("GB", bank_name="Barclays", account_number="12345678",
                   extra={"sort_code": "04-00-04"})
    _place(django_user_model, django_capture_on_commit_callbacks, "GB", world, "our-gb@x.com")

    body = mail.outbox[0].body
    assert "OUR" in body
    assert "all transfer charges" in body.lower()


def test_ng_bank_details_email_does_not_ask_for_our_charges(
    django_user_model, settings, django_capture_on_commit_callbacks
):
    """A domestic NG transfer has no correspondent chain — the paragraph must NOT appear,
    or it's noise that trains the customer to ignore the email."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    world = _world("NG", bank_name="GTBank", account_number="0123456789")
    _place(django_user_model, django_capture_on_commit_callbacks, "NG", world, "our-ng@x.com")

    body = mail.outbox[0].body
    assert "OUR" not in body
    assert "all transfer charges" not in body.lower()


def test_order_received_states_the_24_hour_deadline(
    django_user_model, settings, django_capture_on_commit_callbacks
):
    """Stock is held for 1440 minutes and then released. The customer is never told —
    so nothing makes them transfer today rather than Saturday, and the order dies."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    world = _world("NG", bank_name="GTBank", account_number="0123456789")
    _place(django_user_model, django_capture_on_commit_callbacks, "NG", world, "ttl@x.com")

    body = mail.outbox[0].body
    assert "24 hours" in body


def test_ng_order_received_still_shows_the_plain_bank_fields(
    django_user_model, settings, django_capture_on_commit_callbacks
):
    """The simple market has no `extra` at all — guard the iteration against regressing it."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    world = _world("NG", bank_name="GTBank", account_number="0123456789")
    r = _place(django_user_model, django_capture_on_commit_callbacks, "NG", world, "ng@x.com")

    body = mail.outbox[0].body
    assert "GTBank" in body
    assert "Toke Cosmetics Ltd" in body
    assert "0123456789" in body
    assert r.data["order_number"] in body
    assert "₦3,500.00" in body  # charset intact — a broken one renders this "â‚¦"
