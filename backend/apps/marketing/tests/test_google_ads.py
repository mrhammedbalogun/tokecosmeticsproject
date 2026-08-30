"""The Google Ads Data Manager adapter.

The body shape here is not guessed: it was validated against the LIVE API on 2026-08-30
with `validateOnly: true` against Toke's own ad account, and returned HTTP 200 both bare
and with the full hashed-user-data block. These tests pin that shape.
"""
from __future__ import annotations

import base64
import hashlib
import json
from decimal import Decimal

import httpx
import pytest

from apps.marketing.channels.google_ads import (
    GoogleAdsChannel, _google_email, _service_account,
)
from apps.marketing.payloads import PURCHASE, ContentItem, ConversionPayload, UserSignals

pytestmark = pytest.mark.django_db


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def payload(**kwargs) -> ConversionPayload:
    defaults = dict(
        event_name=PURCHASE,
        event_id="TC-100147",
        event_time=1700000000,
        currency="NGN",
        value=Decimal("47500.00"),
        order_number="TC-100147",
        contents=(ContentItem(content_id="SKU-1", quantity=2, item_price=Decimal("2500.00")),),
        user=UserSignals(
            email="Amina@Example.com",
            phone="+2348012345678",
            first_name="Amina",
            last_name="Bello",
            country="NG",
            postcode="101233",
            click_ids={"gclid": "GCLICK", "ts": 1699999000},
        ),
    )
    defaults.update(kwargs)
    return ConversionPayload(**defaults)


def channel(**kwargs) -> GoogleAdsChannel:
    defaults = dict(pixel_id="AW-123", access_token="", account_id="3352855298",
                    destination_id="7577766208")
    defaults.update(kwargs)
    return GoogleAdsChannel(**defaults)


# ── the gmail trap ──────────────────────────────────────────────────────────────────


def test_google_strips_gmail_dots_and_plus_tags_before_hashing():
    """**The trap this adapter exists to avoid.**

    Google treats `a.m.i.n.a+shop@gmail.com` and `amina@gmail.com` as one mailbox and
    hashes them identically. Meta, TikTok and Snapchat do NOT — `hashing.normalize_email`
    is deliberately literal for their sake. Sending the shared hash to Google silently
    matches no Gmail customer at all, which for a Nigerian consumer store is most of the
    list, and nothing anywhere reports an error.
    """
    assert _google_email("a.m.i.n.a+shop@gmail.com") == sha("amina@gmail.com")
    assert _google_email("AMINA@GMAIL.COM") == sha("amina@gmail.com")
    assert _google_email("amina@googlemail.com") == sha("amina@googlemail.com")


def test_the_gmail_rule_is_NOT_applied_to_other_domains():
    """Applying it everywhere would break every non-Google mailbox where a dot is
    significant — which is all of them."""
    assert _google_email("a.m.i.n.a@yahoo.com") == sha("a.m.i.n.a@yahoo.com")
    assert _google_email("amina+shop@tokecosmetics.com") == sha("amina+shop@tokecosmetics.com")


def test_google_normalisation_differs_from_the_shared_one_on_purpose():
    from apps.marketing import hashing

    gmail = "a.m.i.n.a@gmail.com"
    assert _google_email(gmail) != hashing.hashed_email(gmail), (
        "if these ever agree, one of the two platforms is being sent the wrong hash"
    )


def test_a_junk_address_yields_nothing_rather_than_a_hash_of_nonsense():
    assert _google_email("not-an-email") == ""
    assert _google_email("") == ""
    assert _google_email("@gmail.com") == ""


# ── the request body ────────────────────────────────────────────────────────────────


def test_the_destination_names_the_customer_and_the_conversion_action():
    body = channel().build(payload())
    dest = body["destinations"][0]
    assert dest["operatingAccount"] == {"accountType": "GOOGLE_ADS", "accountId": "3352855298"}
    assert dest["productDestinationId"] == "7577766208"


def test_the_transaction_id_is_the_order_number():
    """Google deduplicates on transactionId, exactly as the other three do on event_id.
    Anything else here double-counts every sale that arrives both ways."""
    assert channel().build(payload())["events"][0]["transactionId"] == "TC-100147"


def test_encoding_is_declared_as_hex_because_our_hashes_are_hex():
    # Declaring BASE64 with hex values is accepted by the API and matches nobody.
    assert channel().build(payload())["encoding"] == "HEX"


def test_the_timestamp_is_rfc3339_utc():
    # 1700000000 is 2023-11-14T22:13:20Z. The trailing Z is the only timezone we should
    # ever assert — `Order.placed_at` is stored in UTC.
    assert channel().build(payload())["events"][0]["eventTimestamp"] == "2023-11-14T22:13:20Z"


def test_user_identifiers_carry_email_phone_and_a_complete_address():
    identifiers = channel().build(payload())["events"][0]["userData"]["userIdentifiers"]
    by_key = {k: v for i in identifiers for k, v in i.items()}
    assert by_key["emailAddress"] == sha("amina@example.com")
    assert by_key["phoneNumber"] == sha("2348012345678")
    assert by_key["address"]["givenName"] == sha("amina")
    # Region and postal code go in the CLEAR — hashing them matches nothing.
    assert by_key["address"]["regionCode"] == "NG"
    assert by_key["address"]["postalCode"] == "101233"


def test_a_half_populated_address_is_dropped_rather_than_sent():
    """A partial address matches nobody and still counts against the ten-identifier
    ceiling."""
    signals = UserSignals(email="a@b.com", first_name="Amina", country="NG")  # no surname
    identifiers = channel().build(payload(user=signals))["events"][0]["userData"]["userIdentifiers"]
    assert not any("address" in i for i in identifiers)


def test_an_address_without_a_postcode_is_dropped_not_sent_incomplete():
    """**Measured against the live API on 2026-08-30, and not what the docs imply.**

    `postalCode` is REQUIRED on an address identifier. Sending one without it is not a
    dropped identifier — it is a 400 for the WHOLE batch:

        events[0].user_data.user_identifiers[2].address.postal_code
        "Required field is missing." REQUIRED_FIELD_MISSING

    Nigerian addresses very often have no postcode, so this is the common case in Toke's
    main market, not an edge case. The conversion still goes — on email and phone, which
    are the stronger identifiers anyway.
    """
    no_postcode = UserSignals(
        email="a@b.com", phone="+2348012345678",
        first_name="Amina", last_name="Bello", country="NG", postcode="",
    )
    identifiers = channel().build(
        payload(user=no_postcode)
    )["events"][0]["userData"]["userIdentifiers"]

    assert not any("address" in i for i in identifiers), "an incomplete address 400s the batch"
    # And the event is still worth sending.
    keys = {k for i in identifiers for k in i}
    assert keys == {"emailAddress", "phoneNumber"}


def test_a_complete_address_is_sent_with_region_and_postcode_in_the_clear():
    identifiers = channel().build(payload())["events"][0]["userData"]["userIdentifiers"]
    address = next(i["address"] for i in identifiers if "address" in i)
    assert set(address) == {"givenName", "familyName", "regionCode", "postalCode"}
    assert address["regionCode"] == "NG" and address["postalCode"] == "101233"


def test_exactly_one_click_id_is_sent():
    signals = UserSignals(click_ids={"gclid": "G1", "wbraid": "W1", "gbraid": "B1"})
    ads = channel().build(payload(user=signals))["events"][0]["adIdentifiers"]
    assert ads == {"gclid": "G1"}, "Google accepts one click id; gclid is the preferred one"


def test_an_order_with_no_click_id_still_sends_on_its_user_data():
    """A customer who reached the shop another way but matches on email is still a
    conversion Google can attribute."""
    event = channel().build(payload(user=UserSignals(email="a@b.com")))["events"][0]
    assert "adIdentifiers" not in event
    assert event["userData"]["userIdentifiers"]


def test_validate_only_is_absent_unless_asked_for():
    assert "validateOnly" not in channel().build(payload())
    assert channel(validate_only=True).build(payload())["validateOnly"] is True


# ── responses ───────────────────────────────────────────────────────────────────────


def test_a_bare_request_id_is_success():
    result = channel().interpret(httpx.Response(200, json={"requestId": "v-abc"}))
    assert result.ok is True


def test_anything_beyond_the_request_id_in_a_200_is_a_failure():
    """Data Manager reports per-event problems inside a 200, the same trap TikTok sets
    with its envelope code. A bare status check marks a rejected batch as sent."""
    refused = httpx.Response(200, json={
        "requestId": "v-abc",
        "errors": [{"reason": "INVALID_CONVERSION_ACTION"}],
    })
    result = channel().interpret(refused)
    assert result.ok is False
    assert result.retryable is False
    assert "INVALID_CONVERSION_ACTION" in result.excerpt


def test_a_401_clears_the_cached_token_and_retries():
    from django.core.cache import cache

    from apps.marketing.channels.google_ads import TOKEN_CACHE_KEY

    cache.set(TOKEN_CACHE_KEY, "stale-token", 60)
    result = channel().interpret(httpx.Response(401, text="Invalid Credentials"))

    assert result.retryable is True
    assert cache.get(TOKEN_CACHE_KEY) is None, "a stale token must not survive a 401"


# ── credentials ─────────────────────────────────────────────────────────────────────


def test_a_missing_credential_fails_the_row_instead_of_raising(settings):
    """The outbox wants a `failed` row with a reason, not a traceback out of a Celery
    task."""
    settings.GOOGLE_ADS_DM_CREDENTIALS_B64 = ""
    result = channel().send({})
    assert result.ok is False
    assert result.retryable is False
    assert "GOOGLE_ADS_DM_CREDENTIALS_B64" in result.excerpt


def test_a_corrupt_credential_says_so_rather_than_crashing(settings):
    settings.GOOGLE_ADS_DM_CREDENTIALS_B64 = "not-base64-at-all!!"
    result = channel().send({})
    assert result.ok is False
    assert "service account key" in result.excerpt


def test_a_well_formed_credential_decodes(settings):
    settings.GOOGLE_ADS_DM_CREDENTIALS_B64 = base64.b64encode(
        json.dumps({"client_email": "sa@x.iam.gserviceaccount.com", "private_key": "-"}).encode()
    ).decode()
    assert _service_account()["client_email"] == "sa@x.iam.gserviceaccount.com"


# ── the outbox path ─────────────────────────────────────────────────────────────────


def test_google_is_skipped_until_it_has_a_customer_and_conversion_action(settings):
    """`pixel_id` alone is not enough for this one channel: the browser tag and the
    server API are addressed differently."""
    from apps.marketing.events import enqueue_purchase
    from apps.marketing.models import ConversionEvent
    from apps.marketing.tests.factories import (
        attribution, channel as make_channel, enable_tracking, make_order,
    )

    settings.GOOGLE_ADS_DM_CREDENTIALS_B64 = "x"
    enable_tracking()
    row = make_channel("google_ads", pixel_id="AW-123")  # no server ids
    order = make_order(user=None, email="a@b.com")
    attribution(order)

    enqueue_purchase(order.pk)

    assert ConversionEvent.objects.get(order=order).last_error == "no_server_destination"

    row.server_account_id, row.server_destination_id = "3352855298", "7577766208"
    row.save()
    ConversionEvent.objects.all().delete()
    enqueue_purchase(order.pk)
    assert ConversionEvent.objects.get(order=order).status == "pending"
